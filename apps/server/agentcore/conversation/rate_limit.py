"""Per-user message-send rate limiting — the「速率」防线 that refuses a turn when an
account fires messages too fast (成本配额与计费.md §一).

Orthogonal to quota (总量): rate limiting caps requests-per-window, quota caps
cumulative usage. Enforced at the route layer (alongside ``enforce_quota``) rather
than in middleware, because the cap is per *authenticated user* — middleware only
sees the client IP. It runs first, before any resource-specific DB work, so a
flooding account sheds load early. The limiter is an in-memory sliding window
(single server process); a Redis ZSET impl can replace it behind the
``RateLimiter`` seam for multiple workers.
"""

from __future__ import annotations

import math

from agentcore.config import settings
from agentcore.core.errors import RateLimitedError
from agentcore.middleware.rate_limit import RateLimiter, message_rate_limiter


async def enforce_user_message_rate_limit(
    user_id: str,
    *,
    limiter: RateLimiter | None = None,
    now: float | None = None,
) -> None:
    """Raise :class:`RateLimitedError` if ``user_id`` exceeds the message-send rate.

    No-op when rate limiting is disabled (``rate_limit_enabled`` off) or the cap is
    ``<= 0``. The check is O(1) amortized against an in-memory deque — light enough
    for the turn hot path. Declared ``async`` to keep the call site uniform with
    ``enforce_quota`` and stable should a future Redis limiter make the check
    awaitable.
    """
    if not settings.rate_limit_enabled or settings.user_message_rate_limit_max <= 0:
        return

    limiter = limiter or message_rate_limiter
    decision = limiter.check(user_id, now=now)
    if not decision.allowed:
        retry_after = max(1, math.ceil(decision.retry_after))
        raise RateLimitedError(
            f"操作过于频繁，请约 {retry_after} 秒后再发送。",
            retry_after=decision.retry_after,
        )
