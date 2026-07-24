"""Request rate limiting middleware.

A small in-memory fixed-window limiter for the auth endpoints (login, register,
refresh) to blunt credential-stuffing and registration spam on the public net.
Per-account lockout already lives in the auth service; this adds per-IP throttling
across accounts.

State is process-local, so it assumes a single server process — front with Redis
if you scale to multiple workers. The core ``FixedWindowRateLimiter`` is framework
-free and unit-tested directly; the middleware is the thin ASGI adapter.
"""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from agentcore.config import settings


class FixedWindowRateLimiter:
    """Count requests per key within a fixed window; block once the cap is hit."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """Record a hit for ``key``; return False once it exceeds the window cap."""
        now = time.monotonic() if now is None else now
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        return count <= self._max

    def reset(self) -> None:
        self._hits.clear()


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a limiter check. ``retry_after`` is the seconds until the next
    slot frees (``0`` when allowed)."""

    allowed: bool
    retry_after: float = 0.0


class RateLimiter(Protocol):
    """Swappable limiter seam (成本配额与计费.md §一). The in-memory impl below is
    single-process; a Redis ZSET impl can replace it for multiple workers without
    touching call sites."""

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision: ...

    def reset(self) -> None: ...


class SlidingWindowRateLimiter:
    """Per-key sliding window: at most ``max_requests`` hits within any trailing
    ``window_seconds``.

    Unlike a fixed window, this has no boundary burst (a fixed window can let ~2x
    the cap straddle the reset instant). Keeps a deque of hit timestamps per key,
    evicting those older than the window on each check. A blocked call is **not**
    recorded, so a client that keeps hammering while throttled can't push its own
    reset further out. State is process-local (single server process) — front with
    a Redis ZSET to scale to multiple workers.
    """

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        """Record an allowed hit for ``key`` and return the decision."""
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._max:
            retry_after = hits[0] + self._window - now
            return RateLimitDecision(allowed=False, retry_after=max(0.0, retry_after))
        hits.append(now)
        return RateLimitDecision(allowed=True)

    def reset(self) -> None:
        self._hits.clear()


# Module-level singletons sized from settings; exposed so tests can reset state.
def _build_auth_rate_limiter():
    if settings.rate_limit_backend == "redis":
        try:
            from agentcore.middleware.redis_rate_limit import (
                RedisFixedWindowRateLimiter,
                redis_client,
            )

            return RedisFixedWindowRateLimiter(
                client=redis_client(),
                prefix="rl:auth",
                max_requests=settings.auth_rate_limit_max,
                window_seconds=settings.auth_rate_limit_window_seconds,
            )
        except Exception:
            pass
    return FixedWindowRateLimiter(
        max_requests=settings.auth_rate_limit_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )


def _build_sliding_rate_limiter(*, prefix: str, max_requests: int, window_seconds: float):
    if settings.rate_limit_backend == "redis":
        try:
            from agentcore.middleware.redis_rate_limit import (
                RedisSlidingWindowRateLimiter,
                redis_client,
            )

            return RedisSlidingWindowRateLimiter(
                client=redis_client(),
                prefix=prefix,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        except Exception:
            pass
    return SlidingWindowRateLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
    )


auth_rate_limiter = _build_auth_rate_limiter()
message_rate_limiter = _build_sliding_rate_limiter(
    prefix="rl:msg",
    max_requests=settings.user_message_rate_limit_max,
    window_seconds=settings.user_message_rate_limit_window_seconds,
)
inference_token_mint_limiter = _build_sliding_rate_limiter(
    prefix="rl:inf",
    max_requests=settings.inference_token_mint_max,
    window_seconds=settings.inference_token_mint_window_seconds,
)


def reset_rate_limit_state() -> None:
    """Clear all counters (test isolation between cases)."""
    auth_rate_limiter.reset()
    message_rate_limiter.reset()
    inference_token_mint_limiter.reset()
    from agentcore.conversation.inference_rate_limit import reset_inference_proxy_turn_claims

    reset_inference_proxy_turn_claims()


def get_client_ip(request: Request) -> str:
    """Resolve the client IP using the same trust_proxy / XFF hop rules as rate limiting
    (SEC-008). Auth session bookkeeping must call this — do not re-invent XFF parsing."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            # Take the Nth entry from the RIGHT — the IP appended by your own trusted
            # proxy — not the leftmost (client-controlled, trivially spoofed to rotate
            # the rate-limit key past per-IP throttling). N = number of trusted proxies
            # in front of the app (SEC-008).
            hops = settings.trusted_proxy_hops if settings.trusted_proxy_hops > 0 else 1
            if len(parts) >= hops:
                return parts[-hops]
            # Chain shorter than the configured trusted-proxy count → the request didn't
            # traverse the expected proxies, so XFF is untrustworthy; fall back to the
            # real socket peer rather than honor a (possibly spoofed) shorter chain.
    client = request.client
    return client.host if client else "unknown"


def _client_key(request: Request) -> str:
    return get_client_ip(request)


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Throttle POSTs under the auth path prefix per client IP."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: FixedWindowRateLimiter | None = None,
        path_prefix: str = "/v1/auth/",
    ) -> None:
        super().__init__(app)
        self._limiter = limiter or auth_rate_limiter
        self._path_prefix = path_prefix

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        throttled = (
            settings.rate_limit_enabled
            and request.method == "POST"
            and request.url.path.startswith(self._path_prefix)
        )
        if throttled and not self._limiter.allow(_client_key(request)):
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Slow down and retry shortly.",
                    }
                },
                headers={"Retry-After": str(int(settings.auth_rate_limit_window_seconds))},
            )
        return await call_next(request)
