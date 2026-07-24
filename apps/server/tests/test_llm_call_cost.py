"""llm.call observability must emit cost_nano from the single pricing source."""

from __future__ import annotations

from structlog.testing import capture_logs

from agentcore.llm.observability import log_llm_call
from agentcore.llm.pricing import calculate_cost
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider.protocol import TokenUsage


def _usage() -> TokenUsage:
    return TokenUsage(
        input_tokens=1_000,
        cache_miss_tokens=1_000,
        output_tokens=500,
    )


def test_log_llm_call_emits_cost_nano_from_calculate_cost():
    usage = _usage()
    expected = calculate_cost(DEEPSEEK_V4_FLASH, usage, credential_source="platform").total
    assert expected > 0
    with capture_logs() as caps:
        log_llm_call(
            scenario="chat",
            model=DEEPSEEK_V4_FLASH,
            usage=usage,
            finish_reason="stop",
            latency_ms=42,
            stream=False,
            credential_source="platform",
        )
    call = next(c for c in caps if c.get("event") == "llm.call")
    assert call["cost_nano"] == expected
    assert "input_tokens" in call  # existing fields untouched


def test_log_llm_call_byok_cost_nano_is_zero():
    usage = _usage()
    with capture_logs() as caps:
        log_llm_call(
            scenario="chat",
            model=DEEPSEEK_V4_FLASH,
            usage=usage,
            finish_reason="stop",
            latency_ms=10,
            stream=False,
            credential_source="user",
        )
    call = next(c for c in caps if c.get("event") == "llm.call")
    assert call["cost_nano"] == 0  # billed nano (user path never hits quota)
    assert call.get("cost_estimated_nano", 0) >= 0
    assert call.get("pricing_source") in ("estimated", "unpriced", "user_defined")
