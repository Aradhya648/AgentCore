"""Unit tests for the rate limiters, the auth ASGI middleware, and the per-user
message-send enforcement helper."""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from starlette.requests import Request

from agentcore.config import settings
from agentcore.conversation.rate_limit import enforce_user_message_rate_limit
from agentcore.core.errors import RateLimitedError
from agentcore.middleware.rate_limit import (
    AuthRateLimitMiddleware,
    FixedWindowRateLimiter,
    SlidingWindowRateLimiter,
    _client_key,
)

# --- core limiter ---


def test_allows_up_to_max_then_blocks():
    limiter = FixedWindowRateLimiter(max_requests=3, window_seconds=60)
    assert [limiter.allow("ip", now=0) for _ in range(3)] == [True, True, True]
    assert limiter.allow("ip", now=1) is False


def test_window_resets_after_elapsed():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.allow("ip", now=0) is True
    assert limiter.allow("ip", now=5) is False
    assert limiter.allow("ip", now=11) is True  # fresh window


def test_keys_are_independent():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.allow("a", now=0) is True
    assert limiter.allow("b", now=0) is True
    assert limiter.allow("a", now=0) is False


def test_reset_clears_counters():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.allow("ip", now=0) is True
    assert limiter.allow("ip", now=0) is False
    limiter.reset()
    assert limiter.allow("ip", now=0) is True


# --- middleware ---


def _app(limiter: FixedWindowRateLimiter) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthRateLimitMiddleware, limiter=limiter)

    @app.post("/v1/auth/login")
    async def _login():
        return {"ok": True}

    @app.get("/v1/auth/me")
    async def _me():
        return {"ok": True}

    @app.post("/v1/conversations")
    async def _convos():
        return {"ok": True}

    return app


async def test_middleware_throttles_auth_posts(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60)
    transport = ASGITransport(app=_app(limiter))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post("/v1/auth/login")).status_code == 200
        assert (await c.post("/v1/auth/login")).status_code == 200
        blocked = await c.post("/v1/auth/login")
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert blocked.headers.get("retry-after")


async def test_middleware_ignores_get_and_non_auth_paths():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60)
    transport = ASGITransport(app=_app(limiter))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # GET under the auth prefix is not throttled (only POST is)...
        for _ in range(5):
            assert (await c.get("/v1/auth/me")).status_code == 200
        # ...and a non-auth POST is never throttled.
        for _ in range(5):
            assert (await c.post("/v1/conversations")).status_code == 200


# --- client-key derivation (X-Forwarded-For trust, SEC-008) ---


def _req(*, xff: str | None, peer: str = "203.0.113.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 12345)})


def test_client_key_ignores_xff_when_proxy_untrusted(monkeypatch):
    # Default posture: don't trust XFF at all → key off the real socket peer.
    monkeypatch.setattr(settings, "trust_proxy", False)
    assert _client_key(_req(xff="1.2.3.4, 5.6.7.8", peer="203.0.113.9")) == "203.0.113.9"


def test_client_key_takes_rightmost_hop_when_trusted(monkeypatch):
    # SEC-008: one trusted proxy → the trustworthy client IP is the entry IT appended
    # (rightmost), not the spoofable leftmost the client controls.
    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert _client_key(_req(xff="spoofed-by-client, 198.51.100.7")) == "198.51.100.7"


def test_client_key_honors_multiple_trusted_hops(monkeypatch):
    # Two trusted proxies (CDN + nginx) → the client is the 2nd entry from the right.
    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert _client_key(_req(xff="spoof, 198.51.100.7, 70.0.0.2")) == "198.51.100.7"


def test_client_key_falls_back_to_peer_when_chain_too_short(monkeypatch):
    # A spoofer sending a short XFF can't downgrade to a controlled value: a chain
    # shorter than the trusted-hop count is untrustworthy → fall back to the peer.
    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert _client_key(_req(xff="1.2.3.4", peer="10.0.0.1")) == "10.0.0.1"


# --- sliding-window limiter ---


def test_sliding_window_allows_up_to_max_then_blocks():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    assert [limiter.check("u", now=0).allowed for _ in range(3)] == [True, True, True]
    assert limiter.check("u", now=1).allowed is False


def test_sliding_window_slides_as_old_hits_expire():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10)
    assert limiter.check("u", now=0).allowed is True
    assert limiter.check("u", now=5).allowed is True
    assert limiter.check("u", now=9).allowed is False  # full within trailing 10s
    assert limiter.check("u", now=10).allowed is True  # the t=0 hit aged out


def test_sliding_window_reports_retry_after():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.check("u", now=0).allowed is True
    decision = limiter.check("u", now=4)
    assert decision.allowed is False
    assert decision.retry_after == 6  # oldest hit (t=0) frees at t=10


def test_sliding_window_blocked_call_is_not_recorded():
    # A throttled client that keeps hammering must not push its own reset further out.
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.check("u", now=0).allowed is True
    assert limiter.check("u", now=5).allowed is False
    assert limiter.check("u", now=9).allowed is False  # still only the t=0 hit counts
    assert limiter.check("u", now=10).allowed is True  # t=0 aged out on schedule


def test_sliding_window_keys_are_independent():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.check("a", now=0).allowed is True
    assert limiter.check("b", now=0).allowed is True
    assert limiter.check("a", now=0).allowed is False


def test_sliding_window_reset_clears_state():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.check("u", now=0).allowed is True
    assert limiter.check("u", now=0).allowed is False
    limiter.reset()
    assert limiter.check("u", now=0).allowed is True


# --- enforce_user_message_rate_limit ---


async def test_enforce_passes_under_limit():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    await enforce_user_message_rate_limit("u", limiter=limiter, now=0)
    await enforce_user_message_rate_limit("u", limiter=limiter, now=0)  # no raise


async def test_enforce_raises_rate_limited_when_over(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "user_message_rate_limit_max", 20)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    await enforce_user_message_rate_limit("u", limiter=limiter, now=0)
    with pytest.raises(RateLimitedError) as ei:
        await enforce_user_message_rate_limit("u", limiter=limiter, now=4)
    assert ei.value.code == "RATE_LIMITED"
    assert ei.value.status_code == 429
    assert ei.value.retry_after == 6


async def test_enforce_noop_when_dimension_disabled(monkeypatch):
    # max <= 0 disables this dimension even if the limiter itself is saturated.
    monkeypatch.setattr(settings, "user_message_rate_limit_max", 0)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    limiter.check("u", now=0)  # saturate
    await enforce_user_message_rate_limit("u", limiter=limiter, now=0)  # no raise


async def test_enforce_noop_when_rate_limiting_globally_off(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    limiter.check("u", now=0)  # saturate
    await enforce_user_message_rate_limit("u", limiter=limiter, now=0)  # no raise
