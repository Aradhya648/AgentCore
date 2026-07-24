"""Unit tests for the Redis-backed limiters — focus on request-level fail-open.

These exercise the limiter classes against fake clients (no live Redis). The core
guarantee under test: a Redis failure *during* a request allows that request
(fail-open) and logs an alertable warning, rather than turning the outage into a
hard 429 for every caller (成本配额与计费.md §一). Happy-path fakes prove the
fail-open is scoped to failures and does not blanket-allow.
"""

import logging

from agentcore.middleware.redis_rate_limit import (
    RedisFixedWindowRateLimiter,
    RedisSlidingWindowRateLimiter,
)

_FAIL_OPEN_LOG = "rate_limit.redis_fail_open"
_LOGGER = "agentcore.middleware.redis_rate_limit"


# --- fakes ---------------------------------------------------------------------------


class _FailingPipe:
    """Queues commands like a redis pipeline but blows up on execute()."""

    def incr(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    def zremrangebyscore(self, *args, **kwargs):
        return self

    def zcard(self, *args, **kwargs):
        return self

    def execute(self):
        raise ConnectionError("redis unavailable")


class _FailingClient:
    """Every Redis interaction raises — stands in for a total backend outage."""

    def pipeline(self):
        return _FailingPipe()

    def zrange(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")

    def zadd(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")

    def expire(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class _OverLimitThenBoomPipe:
    """zcard reports over the cap on a healthy pipeline read."""

    def zremrangebyscore(self, *args, **kwargs):
        return self

    def zcard(self, *args, **kwargs):
        return self

    def execute(self):
        return [0, 99]  # zrem result, zcard count (>= any sane cap)


class _OverLimitThenBoomClient:
    """The count read succeeds (over limit) but the follow-up zrange dies mid-check."""

    def pipeline(self):
        return _OverLimitThenBoomPipe()

    def zrange(self, *args, **kwargs):
        raise ConnectionError("redis died mid-check")


class _WorkingFixedPipe:
    def __init__(self, client):
        self._client = client
        self._key = None

    def incr(self, key):
        self._key = key
        return self

    def expire(self, *args, **kwargs):
        return self

    def execute(self):
        self._client.counts[self._key] = self._client.counts.get(self._key, 0) + 1
        return [self._client.counts[self._key], True]


class _WorkingFixedClient:
    """Minimal INCR emulation so the happy path is real, not mocked-to-allow."""

    def __init__(self):
        self.counts: dict[str, int] = {}

    def pipeline(self):
        return _WorkingFixedPipe(self)


class _WorkingSlidingPipe:
    def __init__(self, client):
        self._client = client
        self._key = None
        self._cutoff = 0.0

    def zremrangebyscore(self, key, _lo, hi):
        self._key = key
        self._cutoff = hi
        return self

    def zcard(self, key):
        self._key = key
        return self

    def execute(self):
        zset = self._client.zsets.setdefault(self._key, {})
        for member in [m for m, score in zset.items() if score <= self._cutoff]:
            del zset[member]
        return [0, len(zset)]


class _WorkingSlidingClient:
    """Minimal sorted-set emulation for the sliding-window happy path."""

    def __init__(self):
        self.zsets: dict[str, dict[str, float]] = {}

    def pipeline(self):
        return _WorkingSlidingPipe(self)

    def zrange(self, key, start, end, withscores=False):
        items = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        chunk = items[start:] if end == -1 else items[start : end + 1]
        return chunk if withscores else [m for m, _ in chunk]

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def expire(self, *args, **kwargs):
        return None


# --- fixed window: fail-open ---------------------------------------------------------


def test_fixed_window_fails_open_on_redis_error(caplog):
    limiter = RedisFixedWindowRateLimiter(
        client=_FailingClient(), prefix="rl:auth", max_requests=1, window_seconds=60
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        # Even repeated hits past the cap are allowed while the backend is down.
        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is True
    assert _FAIL_OPEN_LOG in caplog.text


def test_fixed_window_enforces_when_redis_healthy():
    # Proves fail-open is scoped to failures: a working backend still blocks over cap.
    limiter = RedisFixedWindowRateLimiter(
        client=_WorkingFixedClient(), prefix="rl:auth", max_requests=2, window_seconds=60
    )
    assert [limiter.allow("ip", now=0) for _ in range(2)] == [True, True]
    assert limiter.allow("ip", now=0) is False


# --- sliding window: fail-open -------------------------------------------------------


def test_sliding_window_fails_open_on_redis_error(caplog):
    limiter = RedisSlidingWindowRateLimiter(
        client=_FailingClient(), prefix="rl:msg", max_requests=1, window_seconds=60
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        decision = limiter.check("u")
    assert decision.allowed is True
    assert decision.retry_after == 0.0
    assert _FAIL_OPEN_LOG in caplog.text


def test_sliding_window_fails_open_when_backend_dies_mid_check(caplog):
    # The count read says "over limit", but the retry-after lookup fails: still allow.
    limiter = RedisSlidingWindowRateLimiter(
        client=_OverLimitThenBoomClient(), prefix="rl:msg", max_requests=1, window_seconds=60
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        decision = limiter.check("u")
    assert decision.allowed is True
    assert _FAIL_OPEN_LOG in caplog.text


def test_sliding_window_enforces_when_redis_healthy():
    limiter = RedisSlidingWindowRateLimiter(
        client=_WorkingSlidingClient(), prefix="rl:msg", max_requests=2, window_seconds=10
    )
    assert limiter.check("u", now=0).allowed is True
    assert limiter.check("u", now=1).allowed is True
    blocked = limiter.check("u", now=2)
    assert blocked.allowed is False
    assert blocked.retry_after == 8.0  # oldest hit (t=0) frees at t=10
    assert limiter.check("u", now=11).allowed is True  # window slid; t=0/t=1 aged out
