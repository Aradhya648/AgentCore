"""Unit tests for inference-proxy turn-scoped rate limiting."""

from __future__ import annotations

import pytest

from agentcore.conversation.inference_rate_limit import (
    _TurnClaimGate,
    enforce_inference_proxy_rate_limit,
    enforce_inference_token_mint_rate_limit,
)
from agentcore.core.errors import RateLimitedError
from agentcore.middleware.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_inference_mint_rate_limit_blocks_after_cap(monkeypatch):
    monkeypatch.setattr(
        "agentcore.conversation.inference_rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.inference_rate_limit.settings.inference_token_mint_max",
        2,
    )
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
    await enforce_inference_token_mint_rate_limit("u1", limiter=limiter, now=0.0)
    await enforce_inference_token_mint_rate_limit("u1", limiter=limiter, now=0.0)
    with pytest.raises(RateLimitedError):
        await enforce_inference_token_mint_rate_limit("u1", limiter=limiter, now=0.0)


@pytest.mark.asyncio
async def test_proxy_rate_limit_same_message_id_counts_once(monkeypatch):
    """Multi-step sidecar turns share one ticket under the same message_id."""
    monkeypatch.setattr(
        "agentcore.conversation.inference_rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.user_message_rate_limit_max",
        20,
    )
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    claims = _TurnClaimGate(ttl_seconds=7200.0)

    await enforce_inference_proxy_rate_limit(
        "u1", message_id="turn-a", limiter=limiter, turn_claims=claims, now=0.0
    )
    # Same turn, many LLM calls — must not raise.
    await enforce_inference_proxy_rate_limit(
        "u1", message_id="turn-a", limiter=limiter, turn_claims=claims, now=1.0
    )
    await enforce_inference_proxy_rate_limit(
        "u1", message_id="turn-a", limiter=limiter, turn_claims=claims, now=2.0
    )


@pytest.mark.asyncio
async def test_proxy_rate_limit_distinct_turns_consume_tickets(monkeypatch):
    monkeypatch.setattr(
        "agentcore.conversation.inference_rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.user_message_rate_limit_max",
        20,
    )
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    claims = _TurnClaimGate(ttl_seconds=7200.0)

    await enforce_inference_proxy_rate_limit(
        "u1", message_id="turn-a", limiter=limiter, turn_claims=claims, now=0.0
    )
    with pytest.raises(RateLimitedError):
        await enforce_inference_proxy_rate_limit(
            "u1", message_id="turn-b", limiter=limiter, turn_claims=claims, now=1.0
        )


@pytest.mark.asyncio
async def test_proxy_rate_limit_missing_message_id_charges_every_request(monkeypatch):
    monkeypatch.setattr(
        "agentcore.conversation.inference_rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.user_message_rate_limit_max",
        20,
    )
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    claims = _TurnClaimGate(ttl_seconds=7200.0)

    await enforce_inference_proxy_rate_limit(
        "u1", message_id=None, limiter=limiter, turn_claims=claims, now=0.0
    )
    with pytest.raises(RateLimitedError):
        await enforce_inference_proxy_rate_limit(
            "u1", message_id=None, limiter=limiter, turn_claims=claims, now=1.0
        )


@pytest.mark.asyncio
async def test_proxy_rate_limit_refused_turn_not_claimed(monkeypatch):
    """A 429 on the first call must not mark the turn claimed (retry still gated)."""
    monkeypatch.setattr(
        "agentcore.conversation.inference_rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        "agentcore.conversation.rate_limit.settings.user_message_rate_limit_max",
        20,
    )
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10.0)
    claims = _TurnClaimGate(ttl_seconds=7200.0)

    await enforce_inference_proxy_rate_limit(
        "u1", message_id="turn-a", limiter=limiter, turn_claims=claims, now=0.0
    )
    with pytest.raises(RateLimitedError):
        await enforce_inference_proxy_rate_limit(
            "u1", message_id="turn-b", limiter=limiter, turn_claims=claims, now=1.0
        )
    # Still blocked — turn-b was never claimed.
    with pytest.raises(RateLimitedError):
        await enforce_inference_proxy_rate_limit(
            "u1", message_id="turn-b", limiter=limiter, turn_claims=claims, now=2.0
        )
