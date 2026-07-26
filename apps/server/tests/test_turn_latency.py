"""Phase-0 turn latency probe: anchor, first-chunk once, content vs tool race."""

from __future__ import annotations

import time

import pytest

from agentcore.core.log_context import log_context
from agentcore.llm.provider.protocol import LLMChunk, LLMRequest, ToolCallDelta
from agentcore.runtime.engine.stream import stream_llm_round
from agentcore.runtime.turn_latency import (
    TurnLatencyProbe,
    bind_turn_latency,
    get_turn_latency,
    reset_turn_latency,
)


def test_probe_as_log_fields_always_has_four_keys_null_not_zero():
    probe = TurnLatencyProbe(anchor_mono=time.monotonic())
    fields = probe.as_log_fields()
    assert set(fields) == {
        "prepare_ms",
        "assemble_ms",
        "ttft_reasoning_ms",
        "ttft_content_ms",
    }
    assert all(v is None for v in fields.values())


def test_prepare_assemble_are_wall_clock_not_fake_zero():
    probe = TurnLatencyProbe(anchor_mono=time.monotonic())
    probe.mark_prepare(12)
    probe.mark_assemble(34)
    # Second mark ignored (first wins).
    probe.mark_prepare(999)
    probe.mark_assemble(999)
    assert probe.prepare_ms == 12
    assert probe.assemble_ms == 34


def test_ttft_relative_to_anchor_and_first_chunk_only():
    anchor = time.monotonic() - 0.05  # ~50ms ago
    probe = TurnLatencyProbe(anchor_mono=anchor)
    assert probe.begin_captain_stream() is True
    probe.note_reasoning_chunk()
    first_r = probe.ttft_reasoning_ms
    assert first_r is not None and first_r >= 40
    probe.note_reasoning_chunk()
    assert probe.ttft_reasoning_ms == first_r  # once only

    probe.note_content_or_tool_chunk()
    first_c = probe.ttft_content_ms
    assert first_c is not None and first_c >= first_r
    probe.note_content_or_tool_chunk()
    assert probe.ttft_content_ms == first_c

    probe.end_captain_stream()
    # Subsequent streams do not re-arm.
    assert probe.begin_captain_stream() is False
    probe.note_reasoning_chunk()
    assert probe.ttft_reasoning_ms == first_r


def test_content_vs_tool_whichever_first():
    probe = TurnLatencyProbe(anchor_mono=time.monotonic())
    assert probe.begin_captain_stream()
    # Tool arrives first → content TTFT set; later content does not overwrite.
    probe.note_content_or_tool_chunk()  # tool path uses same note
    t0 = probe.ttft_content_ms
    assert t0 is not None
    time.sleep(0.01)
    probe.note_content_or_tool_chunk()
    assert probe.ttft_content_ms == t0


def test_clear_ttft_on_retry_within_first_stream():
    probe = TurnLatencyProbe(anchor_mono=time.monotonic())
    assert probe.begin_captain_stream()
    probe.note_reasoning_chunk()
    assert probe.ttft_reasoning_ms is not None
    probe.clear_ttft()
    assert probe.ttft_reasoning_ms is None
    assert probe.ttft_content_ms is None
    probe.note_content_or_tool_chunk()
    assert probe.ttft_content_ms is not None


class _ScriptedProvider:
    def __init__(self, chunks: list[LLMChunk]) -> None:
        self._chunks = chunks
        self._name = "scripted"

    async def stream(self, request: LLMRequest):
        for c in self._chunks:
            yield c


def _req() -> LLMRequest:
    return LLMRequest(messages=[], model="m", scenario="chat")


@pytest.mark.asyncio
async def test_stream_records_ttft_for_captain_first_stream_only():
    probe, token = bind_turn_latency(time.monotonic() - 0.02)
    try:
        with log_context(cost_role="captain"):
            provider = _ScriptedProvider(
                [
                    LLMChunk(delta_reasoning="think"),
                    LLMChunk(delta_content="hi"),
                    LLMChunk(finish_reason="stop"),
                ]
            )
            seen: list[str] = []
            await stream_llm_round(provider, _req(), seen.append, lambda _d: None)
            assert probe.ttft_reasoning_ms is not None
            assert probe.ttft_content_ms is not None
            assert probe.ttft_reasoning_ms <= probe.ttft_content_ms
            r0, c0 = probe.ttft_reasoning_ms, probe.ttft_content_ms

            # Second captain stream must not overwrite.
            provider2 = _ScriptedProvider(
                [
                    LLMChunk(delta_reasoning="later"),
                    LLMChunk(delta_content="later"),
                    LLMChunk(finish_reason="stop"),
                ]
            )
            await stream_llm_round(provider2, _req(), seen.append, lambda _d: None)
            assert probe.ttft_reasoning_ms == r0
            assert probe.ttft_content_ms == c0
    finally:
        reset_turn_latency(token)


@pytest.mark.asyncio
async def test_stream_tool_before_content_sets_ttft_content():
    probe, token = bind_turn_latency(time.monotonic())
    try:
        with log_context(cost_role="captain"):
            provider = _ScriptedProvider(
                [
                    LLMChunk(
                        delta_tool_calls=[
                            ToolCallDelta(index=0, id="c1", function_name="web_search")
                        ]
                    ),
                    LLMChunk(delta_content="ignored-for-ttft"),
                    LLMChunk(finish_reason="tool_calls"),
                ]
            )
            await stream_llm_round(provider, _req(), lambda _d: None, lambda _d: None)
            assert probe.ttft_content_ms is not None
            assert probe.ttft_reasoning_ms is None
    finally:
        reset_turn_latency(token)


@pytest.mark.asyncio
async def test_stream_worker_does_not_record_ttft():
    probe, token = bind_turn_latency(time.monotonic())
    try:
        with log_context(cost_role="member"):
            provider = _ScriptedProvider(
                [
                    LLMChunk(delta_content="worker"),
                    LLMChunk(finish_reason="stop"),
                ]
            )
            await stream_llm_round(provider, _req(), lambda _d: None, lambda _d: None)
            assert probe.ttft_content_ms is None
            assert probe.ttft_reasoning_ms is None
            # Captain stream later still arms (worker did not consume the slot).
        with log_context(cost_role="captain"):
            provider2 = _ScriptedProvider(
                [
                    LLMChunk(delta_content="ceo"),
                    LLMChunk(finish_reason="stop"),
                ]
            )
            await stream_llm_round(provider2, _req(), lambda _d: None, lambda _d: None)
            assert probe.ttft_content_ms is not None
    finally:
        reset_turn_latency(token)


def test_bind_get_reset_contextvar():
    assert get_turn_latency() is None
    probe, token = bind_turn_latency()
    assert get_turn_latency() is probe
    reset_turn_latency(token)
    assert get_turn_latency() is None
