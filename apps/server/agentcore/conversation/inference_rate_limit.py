"""Rate limit helpers for inference-token minting and the sidecar LLM proxy."""

from __future__ import annotations

import math
import time

from agentcore.config import settings
from agentcore.conversation.rate_limit import enforce_user_message_rate_limit
from agentcore.core.errors import RateLimitedError
from agentcore.middleware.rate_limit import RateLimiter, inference_token_mint_limiter


class _TurnClaimGate:
    """Process-local once-per-turn gate so multi-step proxy calls share one rate ticket.

    Claim only after the shared user-message limiter accepts the turn — a refused
    first request must not mark the turn as claimed (that would bypass the cap on
    retry). TTL tracks the inference-token lifetime so a long agent loop is not
    re-charged mid-turn when the message-rate window rolls.
    """

    def __init__(self, *, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._claimed: dict[str, float] = {}

    def already_claimed(self, key: str, *, now: float) -> bool:
        ts = self._claimed.get(key)
        if ts is None:
            return False
        if now - ts >= self._ttl:
            del self._claimed[key]
            return False
        return True

    def claim(self, key: str, *, now: float) -> None:
        self._claimed[key] = now
        if len(self._claimed) > 10_000:
            cutoff = now - self._ttl
            self._claimed = {k: t for k, t in self._claimed.items() if t > cutoff}

    def reset(self) -> None:
        self._claimed.clear()


# Sidecar turns outlive the 60s message window; align claim TTL with token life.
_proxy_turn_claims = _TurnClaimGate(
    ttl_seconds=float(settings.inference_token_expire_minutes * 60),
)


def reset_inference_proxy_turn_claims() -> None:
    """Clear turn-claim state (test isolation)."""
    _proxy_turn_claims.reset()


async def enforce_inference_token_mint_rate_limit(
    user_id: str,
    *,
    limiter: RateLimiter | None = None,
    now: float | None = None,
) -> None:
    """Raise :class:`RateLimitedError` if ``user_id`` mints inference tokens too fast."""
    if not settings.rate_limit_enabled or settings.inference_token_mint_max <= 0:
        return

    limiter = limiter or inference_token_mint_limiter
    decision = limiter.check(user_id, now=now)
    if not decision.allowed:
        retry_after = max(1, math.ceil(decision.retry_after))
        raise RateLimitedError(
            f"推理令牌申请过于频繁，请约 {retry_after} 秒后再试。",
            retry_after=decision.retry_after,
        )


async def enforce_inference_proxy_rate_limit(
    user_id: str,
    *,
    message_id: str | None = None,
    limiter: RateLimiter | None = None,
    turn_claims: _TurnClaimGate | None = None,
    now: float | None = None,
) -> None:
    """Charge the shared user-message rate limit once per sidecar turn.

    Sidecar agent loops issue many ``/chat/completions`` under one
    ``X-AgentCore-Message``; only the first accepted call for that ``message_id``
    consumes a ticket from ``message_rate_limiter``. Missing ``message_id``
    charges every request (untraced / abuse path). Reuses
    ``user_message_rate_limit_*`` — no separate proxy cap.
    """
    if not settings.rate_limit_enabled or settings.user_message_rate_limit_max <= 0:
        return

    now = time.monotonic() if now is None else now
    claims = turn_claims if turn_claims is not None else _proxy_turn_claims

    if message_id:
        turn_key = f"{user_id}:{message_id}"
        if claims.already_claimed(turn_key, now=now):
            return

    await enforce_user_message_rate_limit(user_id, limiter=limiter, now=now)

    if message_id:
        claims.claim(f"{user_id}:{message_id}", now=now)
