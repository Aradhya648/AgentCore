"""Tests for the single pricing function (llm.pricing).

Pins the money math: input is split by cache hit/miss, output includes
reasoning, everything is integer nano-USD, and an unknown model degrades to the
Flash tier instead of crashing. Prices are asserted against the authoritative
table in docs/05-平台与运维/平台LLM接入.md (DeepSeek) / api-docs.deepseek.com.
"""

import pytest
from structlog.testing import capture_logs

from agentcore.config import settings
from agentcore.llm.pricing import (
    DOUBAO_SEED_TURBO,
    NANO_PER_USD,
    PLATFORM_GPT_4O,
    cache_savings,
    calculate_cost,
    nano_usd_to_cny,
    pricing_for_model,
)
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO
from agentcore.llm.provider.protocol import TokenUsage


@pytest.fixture(autouse=True)
def _platform_billing(monkeypatch):
    """Platform pricing table tests assume operator billing, not BYOK zero-cost."""
    monkeypatch.setattr(settings, "billing_mode", "platform")


def _usage(**kw: int) -> TokenUsage:
    return TokenUsage(**kw)


# --- calculate_cost: per-1M prices land on exact nano-USD ---


def test_flash_one_million_each_line():
    # 1M cache_miss @ $0.14, 1M output @ $0.28 → exact nano-USD.
    usage = _usage(
        input_tokens=1_000_000,
        cache_miss_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage)
    assert cost.input == 140_000_000  # 0.14 USD
    assert cost.cached == 0
    assert cost.output == 280_000_000  # 0.28 USD
    assert cost.total == 420_000_000  # 0.42 USD
    assert cost.currency == "USD"


def test_input_splits_cache_hit_vs_miss():
    # 1M hit @ $0.0028 + 1M miss @ $0.14: hit is ~50× cheaper. `cached` re-states
    # just the hit portion; `input` is the sum.
    usage = _usage(
        input_tokens=2_000_000,
        cache_hit_tokens=1_000_000,
        cache_miss_tokens=1_000_000,
    )
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage)
    assert cost.cached == 2_800_000  # 0.0028 USD
    assert cost.input == 2_800_000 + 140_000_000
    assert cost.output == 0
    assert cost.total == cost.input


def test_pro_prices():
    usage = _usage(
        input_tokens=1_000_000,
        cache_hit_tokens=1_000_000,
        cache_miss_tokens=0,
        output_tokens=1_000_000,
    )
    cost = calculate_cost(DEEPSEEK_V4_PRO, usage)
    assert cost.cached == 3_625_000  # 0.003625 USD
    assert cost.input == 3_625_000
    assert cost.output == 870_000_000  # 0.87 USD
    assert cost.total == 3_625_000 + 870_000_000


def test_unknown_model_falls_back_to_flash():
    usage = _usage(output_tokens=1_000_000)
    assert calculate_cost("totally-unknown", usage) == calculate_cost(DEEPSEEK_V4_FLASH, usage)


def test_doubao_priced_at_vendor_rate_not_flash():
    # 豆包 must price at its own (Volcengine 0–32K) rate, NOT degrade to Flash — the
    # whole point of adding it to the table. The distortion that motivated this is on
    # output: ¥8/1M ≈ $1.1111 vs Flash's $0.28 (~4× under-count before).
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost(DOUBAO_SEED_TURBO, usage)
    assert cost.input == 111_100_000  # ¥0.8/1M ÷ 7.2 ≈ $0.1111
    assert cost.cached == 0
    assert cost.output == 1_111_100_000  # ¥8/1M ÷ 7.2 ≈ $1.1111
    assert cost != calculate_cost(DEEPSEEK_V4_FLASH, usage)


def test_doubao_does_not_log_pricing_fallback():
    # Now that 豆包 is in the table, a real run must not emit cost.pricing_fallback.
    with capture_logs() as logs:
        calculate_cost(DOUBAO_SEED_TURBO, _usage(input_tokens=26163, output_tokens=1499))
    assert _fallback_logs(logs) == []


# --- cache-split reconciliation: the input bill always matches the prompt ---


def test_cache_split_missing_bills_whole_prompt_as_miss():
    # A proxy/gateway returns standard OpenAI usage: prompt_tokens but NO
    # DeepSeek cache_hit/cache_miss split. The old code priced only hit+miss (both
    # 0) → input billed as 0; reconciliation prices the whole prompt as a miss.
    usage = _usage(input_tokens=1_000_000, cache_hit_tokens=0, cache_miss_tokens=0)
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage)
    assert cost.cached == 0
    assert cost.input == 140_000_000  # 1M @ $0.14 miss, not 0
    assert cost.total == 140_000_000


def test_cache_split_partial_reconciles_remainder_as_miss():
    # Only hits reported (miss field dropped): the uncached remainder
    # (input − hit) is still billed as miss, never lost.
    usage = _usage(input_tokens=1_000_000, cache_hit_tokens=300_000, cache_miss_tokens=0)
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage)
    cached = calculate_cost(DEEPSEEK_V4_FLASH, _usage(cache_hit_tokens=300_000)).cached
    miss = calculate_cost(DEEPSEEK_V4_FLASH, _usage(cache_miss_tokens=700_000)).input
    assert cost.cached == cached
    assert cost.input == cached + miss


def test_native_cache_split_is_a_noop():
    # Native DeepSeek path (hit + miss == prompt): reconciliation must not change
    # the bill — pricing with vs. without input_tokens set is identical.
    with_input = calculate_cost(
        DEEPSEEK_V4_FLASH,
        _usage(input_tokens=2_000_000, cache_hit_tokens=1_000_000, cache_miss_tokens=1_000_000),
    )
    split_only = calculate_cost(
        DEEPSEEK_V4_FLASH,
        _usage(cache_hit_tokens=1_000_000, cache_miss_tokens=1_000_000),
    )
    assert with_input == split_only


# --- pricing fallback is observable, not silent (gap D) ---


def _fallback_logs(logs: list[dict]) -> list[dict]:
    return [e for e in logs if e["event"] == "cost.pricing_fallback"]


def test_unknown_model_logs_pricing_fallback():
    with capture_logs() as logs:
        calculate_cost("totally-unknown", _usage(input_tokens=100, output_tokens=50))
    events = _fallback_logs(logs)
    assert len(events) == 1
    assert events[0]["model"] == "totally-unknown"
    assert events[0]["fallback"] == DEEPSEEK_V4_FLASH
    assert events[0]["log_level"] == "warning"


def test_known_model_does_not_log_fallback():
    with capture_logs() as logs:
        calculate_cost(DEEPSEEK_V4_PRO, _usage(input_tokens=100, output_tokens=50))
    assert _fallback_logs(logs) == []


def test_unknown_model_zero_usage_is_silent():
    # A run that never hit the LLM (no tokens) must not spam a fallback warning.
    with capture_logs() as logs:
        calculate_cost("totally-unknown", _usage())
    assert _fallback_logs(logs) == []


def test_zero_usage_is_zero_cost():
    cost = calculate_cost(DEEPSEEK_V4_FLASH, _usage())
    assert (cost.input, cost.cached, cost.output, cost.total) == (0, 0, 0, 0)


def test_byok_billing_mode_uses_community_estimate_not_platform_ledger():
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1_000_000)
    byok = calculate_cost(DEEPSEEK_V4_PRO, usage, billing_mode="byok")
    platform = calculate_cost(DEEPSEEK_V4_PRO, usage, billing_mode="platform")
    # User path: community estimate (deepseek-v4-pro is in the snapshot), not unpriced 0.
    assert byok.pricing_source == "estimated"
    assert byok.credential_source == "user"
    assert byok.total > 0
    assert platform.total > 0
    assert platform.pricing_source == "curated"
    user = calculate_cost(DEEPSEEK_V4_PRO, usage, credential_source="user")
    assert user.pricing_source == "estimated"
    assert calculate_cost(DEEPSEEK_V4_PRO, usage, credential_source="platform").total > 0


def test_pricing_for_model_user_returns_community_or_none():
    assert pricing_for_model(DEEPSEEK_V4_FLASH, billing_mode="byok") is not None
    assert pricing_for_model(DEEPSEEK_V4_FLASH, billing_mode="platform") is not None
    assert pricing_for_model(DEEPSEEK_V4_FLASH, credential_source="user") is not None
    assert pricing_for_model("totally-unknown-xyz", credential_source="user") is None
    assert pricing_for_model(DEEPSEEK_V4_FLASH, credential_source="platform") is not None


def test_small_token_counts_round_half_up():
    # 100 output tokens @ $0.28/1M = 28_000 nano exactly; 1 token rounds.
    assert calculate_cost(DEEPSEEK_V4_FLASH, _usage(output_tokens=100)).output == 28_000
    # 1 token: 0.28 * 1000 = 280 nano (exact, no rounding needed here).
    assert calculate_cost(DEEPSEEK_V4_FLASH, _usage(output_tokens=1)).output == 280


def test_platform_gpt_models_use_dedicated_cards_not_flash_fallback():
    usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)
    gpt4o = calculate_cost(PLATFORM_GPT_4O, usage)
    flash = calculate_cost(DEEPSEEK_V4_FLASH, usage)
    assert gpt4o.total != flash.total


# --- cache_savings: the「省了多少」彩蛋 ---


def test_cache_savings_is_hit_tokens_times_price_gap():
    usage = _usage(cache_hit_tokens=1_000_000)
    # miss(0.14) − hit(0.0028) = 0.1372 USD over 1M tokens.
    assert cache_savings(DEEPSEEK_V4_FLASH, usage) == 140_000_000 - 2_800_000


def test_no_cache_hits_means_no_savings():
    assert cache_savings(DEEPSEEK_V4_FLASH, _usage(cache_miss_tokens=1_000_000)) == 0


# --- nano_usd_to_cny: display-only conversion, rounded to fen ---


def test_nano_to_cny_rounds_to_fen():
    # 1 USD → 7.2 CNY at the default rate.
    assert nano_usd_to_cny(NANO_PER_USD, 7.2) == 7.2
    # 0.14 USD → 1.008 CNY → 1.01 (round half up to fen).
    assert nano_usd_to_cny(140_000_000, 7.2) == 1.01


def test_nano_to_cny_zero():
    assert nano_usd_to_cny(0, 7.2) == 0.0
