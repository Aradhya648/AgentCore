"""Redis-backed rate limiters (multi-worker safe)."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from agentcore.config import settings
from agentcore.middleware.rate_limit import RateLimitDecision

logger = logging.getLogger(__name__)


def _warn_fail_open(prefix: str, exc: Exception) -> None:
    """Redis unreachable mid-request → allow this request (fail-open) but surface it.

    Availability > strict throttling: a Redis outage must not turn every throttled
    endpoint into a hard outage. This only relaxes the *rate* defense (requests per
    window); the *total-usage* cap lives in the DB-backed quota defense, which never
    routes through Redis and is unaffected (成本配额与计费.md §一). Logged at WARNING
    with a stable key so ops can alert on a degraded limiter.
    """
    logger.warning("rate_limit.redis_fail_open prefix=%s error=%r", prefix, exc)


@dataclass(frozen=True)
class _RedisWindow:
    client: object
    prefix: str
    max_requests: int
    window_seconds: float


def redis_client():
    import redis

    client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    client.ping()
    return client


class RedisFixedWindowRateLimiter:
    """Per-key fixed window using ``INCR`` + ``EXPIRE``."""

    def __init__(self, *, client, prefix: str, max_requests: int, window_seconds: float) -> None:
        self._cfg = _RedisWindow(client, prefix, max_requests, window_seconds)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        window_id = int(now // self._cfg.window_seconds)
        rkey = f"{self._cfg.prefix}:{key}:{window_id}"
        try:
            pipe = self._cfg.client.pipeline()
            pipe.incr(rkey)
            pipe.expire(rkey, int(math.ceil(self._cfg.window_seconds)) + 1)
            count, _ = pipe.execute()
        except Exception as exc:  # broad by design: any Redis/backend failure fails open
            _warn_fail_open(self._cfg.prefix, exc)
            return True
        return int(count) <= self._cfg.max_requests

    def reset(self) -> None:
        for key in self._cfg.client.scan_iter(match=f"{self._cfg.prefix}:*"):
            self._cfg.client.delete(key)


class RedisSlidingWindowRateLimiter:
    """Per-key sliding window using a sorted set of hit timestamps."""

    def __init__(self, *, client, prefix: str, max_requests: int, window_seconds: float) -> None:
        self._cfg = _RedisWindow(client, prefix, max_requests, window_seconds)

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        now = time.time() if now is None else now
        rkey = f"{self._cfg.prefix}:{key}"
        cutoff = now - self._cfg.window_seconds
        try:
            pipe = self._cfg.client.pipeline()
            pipe.zremrangebyscore(rkey, 0, cutoff)
            pipe.zcard(rkey)
            _, count = pipe.execute()
            if int(count) >= self._cfg.max_requests:
                oldest = self._cfg.client.zrange(rkey, 0, 0, withscores=True)
                retry_after = 0.0
                if oldest:
                    retry_after = max(0.0, float(oldest[0][1]) + self._cfg.window_seconds - now)
                return RateLimitDecision(allowed=False, retry_after=retry_after)
            self._cfg.client.zadd(rkey, {str(now): now})
            self._cfg.client.expire(rkey, int(math.ceil(self._cfg.window_seconds)) + 1)
        except Exception as exc:  # broad by design: any Redis/backend failure fails open
            _warn_fail_open(self._cfg.prefix, exc)
            return RateLimitDecision(allowed=True)
        return RateLimitDecision(allowed=True)

    def reset(self) -> None:
        for key in self._cfg.client.scan_iter(match=f"{self._cfg.prefix}:*"):
            self._cfg.client.delete(key)
