"""Per-user MFA verify rate limiting (TOTP / recovery / enroll confirm).

Closes the TOTP brute-force window on admin MFA write paths. Reuses the shared
``RateLimiter`` seam (memory sliding window or Redis) — same pattern as
``conversation.rate_limit`` / inference mint caps.
"""

from __future__ import annotations

import math

from agentcore.config import settings
from agentcore.core.errors import RateLimitedError
from agentcore.middleware.rate_limit import RateLimiter, mfa_verify_rate_limiter


async def enforce_mfa_verify_rate_limit(
    user_id: str,
    *,
    limiter: RateLimiter | None = None,
    now: float | None = None,
) -> None:
    """Raise :class:`RateLimitedError` if ``user_id`` exceeds MFA verify attempts.

    No-op when rate limiting is disabled or the MFA cap is ``<= 0``. Call before
    TOTP / recovery crypto so a locked account sheds load without decrypting.
    """
    if not settings.rate_limit_enabled or settings.mfa_verify_rate_limit_max <= 0:
        return

    limiter = limiter or mfa_verify_rate_limiter
    decision = limiter.check(user_id, now=now)
    if not decision.allowed:
        retry_after = max(1, math.ceil(decision.retry_after))
        raise RateLimitedError(
            f"验证过于频繁，请约 {retry_after} 秒后再试。",
            retry_after=decision.retry_after,
        )
