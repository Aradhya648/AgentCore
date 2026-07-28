"""Pricing layers: community → curated / unpriced + ledger split."""

from __future__ import annotations

from agentcore.llm.pricing import calculate_cost
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.llm.resolve import _model_for_purpose
from agentcore.runtime.costing import priced_call_cost


def _usage(**kw: int) -> TokenUsage:
    return TokenUsage(**kw)


def test_user_unknown_model_is_unpriced_not_flash():
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1000)
    cost = calculate_cost("totally-unknown-xyz", usage, credential_source="user")
    assert cost.pricing_source == "unpriced"
    assert cost.total == 0
    assert cost.credential_source == "user"
    # Platform still falls back to Flash.
    platform = calculate_cost("totally-unknown-xyz", usage, credential_source="platform")
    assert platform.total == calculate_cost(DEEPSEEK_V4_FLASH, usage).total
    assert platform.pricing_source == "curated"


def test_user_community_estimate_when_known_model():
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage, credential_source="user")
    assert cost.pricing_source == "estimated"
    assert cost.total > 0


def test_user_estimate_does_not_enter_billed_nano():
    usage = _usage(input_tokens=10_000, cache_miss_tokens=10_000, output_tokens=100)
    call = priced_call_cost(
        model=DEEPSEEK_V4_FLASH, usage=usage, role="captain", credential_source="user"
    )
    assert call.cost_total_nano == 0
    assert call.cost_estimated_nano > 0
    assert call.cost["pricing_source"] == "estimated"
    platform = priced_call_cost(
        model=DEEPSEEK_V4_FLASH, usage=usage, role="captain", credential_source="platform"
    )
    assert platform.cost_total_nano > 0
    assert platform.cost_estimated_nano == 0


def test_background_model_prefers_user_then_platform(monkeypatch):
    from agentcore.config import settings

    monkeypatch.setattr(settings, "platform_background_model", "platform-bg")
    assert (
        _model_for_purpose(
            "title", chat_model="chat-model", user_background_model="user-bg"
        )
        == "user-bg"
    )
    assert (
        _model_for_purpose("title", chat_model="chat-model", user_background_model=None)
        == "platform-bg"
    )
    monkeypatch.setattr(settings, "platform_background_model", "")
    assert (
        _model_for_purpose("title", chat_model="chat-model", user_background_model=None)
        == "chat-model"
    )
    assert (
        _model_for_purpose("chat", chat_model="chat-model", user_background_model="user-bg")
        == "chat-model"
    )
