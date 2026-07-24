"""SSE generator: idle heartbeat + event passthrough + optional id: seq.

The generator races each event pull against a heartbeat timeout so a turn that is
alive but thinking keeps the connection flowing bytes (the client's stall watchdog
reads those bytes as liveness). No DB, no HTTP — plain async tests
(asyncio_mode=auto).
"""

import asyncio
import json

import pytest

from agentcore.api import sse
from agentcore.runtime.events import EventSink, content_delta


async def test_forwards_events_then_ends_on_close():
    sink = EventSink()
    sink.emit(content_delta("hi"))
    sink.close()

    frames = [frame async for frame in sse._event_generator(sink, None)]

    # The content event is serialized and delivered; nothing idled, so no
    # heartbeat comment is interleaved.
    assert any("content_delta" in f for f in frames)
    assert all(not f.startswith(":") for f in frames)


async def test_emits_heartbeat_while_idle(monkeypatch):
    # Shrink the cadence so the idle branch fires fast and deterministically.
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.02)
    sink = EventSink()
    gen = sse._event_generator(sink, None)
    try:
        # Nothing queued → the pull times out → an SSE comment heartbeat frame.
        first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert first.startswith(":")

        # Real events still come through after heartbeats.
        sink.emit(content_delta("hi"))
        second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert "content_delta" in second

        # Closing the sink ends the stream.
        sink.close()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    finally:
        await gen.aclose()


def test_format_sse_optional_id_line():
    event = content_delta("partial")
    plain = sse._format_sse(event)
    assert "id:" not in plain
    assert plain.startswith(f"event: {event.type}")
    assert "\ndata: " in plain

    with_id = sse._format_sse(event, seq=42)
    assert "\nid: 42\n" in with_id
    # Envelope JSON unchanged — id is a transport line, not a payload field.
    data_line = next(line for line in with_id.split("\n") if line.startswith("data: "))
    envelope = json.loads(data_line[len("data: ") :])
    assert set(envelope) == {"type", "timestamp", "payload"}
    assert "id" not in envelope


def test_pump_sse_style_parser_ignores_id_lines():
    """Mirrors desktop/mobile pumpSSE: only ``data:`` lines are parsed."""
    frame = sse._format_sse(content_delta("hi"), seq=7)
    events = []
    for line in frame.split("\n"):
        if not line.startswith("data: "):
            continue
        events.append(json.loads(line[len("data: ") :]))
    assert len(events) == 1
    assert events[0]["type"] == "content_delta"
    assert events[0]["payload"] == {"delta": "hi"}
