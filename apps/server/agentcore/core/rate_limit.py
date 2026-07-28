"""Framework-free in-process rate limiters.

Used by HTTP middleware, shared spaces, webhooks, and the desktop sidecar.
Keep this module free of Starlette/FastAPI so sidecar import smoke stays light.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Protocol


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
    """Outcome of a limiter check. ``retry_after`` is seconds until the next slot
    frees (``0`` when allowed)."""

    allowed: bool
    retry_after: float = 0.0


class RateLimiter(Protocol):
    """Swappable limiter seam. In-memory impl is single-process; Redis can replace
    it for multiple workers without touching call sites."""

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision: ...

    def reset(self) -> None: ...


class SlidingWindowRateLimiter:
    """Per-key sliding window: at most ``max_requests`` hits within any trailing
    ``window_seconds``.

    A blocked call is **not** recorded. State is process-local.
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
