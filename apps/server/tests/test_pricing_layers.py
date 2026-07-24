"""Pricing layers: user_defined → community → curated / unpriced + ledger split."""

from __future__ import annotations

from decimal import Decimal

from agentcore.llm.pricing import calculate_cost, parse_user_prices
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


def test_user_defined_prices_beat_community_table():
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1_000_000)
    community = calculate_cost(DEEPSEEK_V4_FLASH, usage, credential_source="user")
    assert community.pricing_source == "estimated"
    user_prices = parse_user_prices(
        cache_hit="1", cache_miss="2", output="3"
    )
    assert user_prices is not None
    custom = calculate_cost(
        DEEPSEEK_V4_FLASH,
        usage,
        credential_source="user",
        user_prices=user_prices,
    )
    assert custom.pricing_source == "user_defined"
    assert custom.input == 2_000_000_000  # 1M @ $2
    assert custom.output == 3_000_000_000
    assert custom.total != community.total


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


def test_parse_user_prices_rejects_partial_and_negative():
    assert parse_user_prices(cache_hit="1", cache_miss=None, output="2") is None
    assert parse_user_prices(cache_hit="1", cache_miss="2", output=None) is None
    assert parse_user_prices(cache_hit="-1", cache_miss="1", output="1") is None
    assert parse_user_prices(cache_hit="0.1", cache_miss="0.2", output="0.3") == {
        "cache_hit": Decimal("0.1"),
        "cache_miss": Decimal("0.2"),
        "output": Decimal("0.3"),
    }


def test_parse_user_prices_cache_hit_defaults_to_input_price():
    # Most vendors publish only input/output — cache_hit falls back to the
    # input price (no cache discount), over- rather than under-estimating.
    assert parse_user_prices(cache_miss="0.2", output="0.3") == {
        "cache_hit": Decimal("0.2"),
        "cache_miss": Decimal("0.2"),
        "output": Decimal("0.3"),
    }
