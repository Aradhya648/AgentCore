"""CLIENT_TOOL EPHEMERAL re-hang on SSE attach (refresh while op still open)."""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from agentcore.api import sse
from agentcore.runtime.events import EventSink, content_delta
from agentcore.runtime.events.client_tool_reattach import (
    CHANNEL_BOARD,
    CHANNEL_BOARD_READ,
    CHANNEL_HOST,
    CHANNEL_NOTIFY,
    CHANNEL_WORKSPACE,
    build_client_tool_required,
    client_tool_payload,
)
from agentcore.runtime.events.types import EventType
from agentcore.runtime.interaction import (
    InteractionKind,
    InteractionRegistry,
    default_interaction_registry,
)

pytestmark = pytest.mark.anyio

CONV = "conv-reattach"


def _parse_sse_types(frames: list[str]) -> list[str]:
    types: list[str] = []
    for frame in frames:
        for line in frame.splitlines():
            if line.startswith("event: "):
                types.append(line.removeprefix("event: ").strip())
    return types


def _parse_sse_payloads(frames: list[str]) -> list[dict]:
    out: list[dict] = []
    for frame in frames:
        for line in frame.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line.removeprefix("data: ")))
    return out


async def test_channel_discrimination_builds_correct_event_types():
    registry = InteractionRegistry()
    cases = [
        (
            "req-ws",
            CHANNEL_WORKSPACE,
            EventType.WORKSPACE_OP_REQUIRED.value,
            {"root_id": "r1", "op": "read", "args": {"path": "a.txt"}},
            EventType.WORKSPACE_OP_REQUIRED,
        ),
        (
            "req-host",
            CHANNEL_HOST,
            EventType.HOST_OP_REQUIRED.value,
            {"op": "host_ping", "args": {}},
            EventType.HOST_OP_REQUIRED,
        ),
        (
            "req-board",
            CHANNEL_BOARD,
            EventType.BOARD_OP_REQUIRED.value,
            {"board_id": "b1", "ops": [{"op": "add_node"}], "summary": "x"},
            EventType.BOARD_OP_REQUIRED,
        ),
        (
            "req-bread",
            CHANNEL_BOARD_READ,
            EventType.BOARD_READ_REQUIRED.value,
            {"board_id": "b1", "ids": ["e1"]},
            EventType.BOARD_READ_REQUIRED,
        ),
        (
            "req-notify",
            CHANNEL_NOTIFY,
            EventType.DESKTOP_NOTIFY_REQUIRED.value,
            {"title": "hi", "body": "there"},
            EventType.DESKTOP_NOTIFY_REQUIRED,
        ),
    ]
    for rid, channel, et, params, expected_type in cases:
        fut = registry.create(
            rid,
            CONV,
            kind=InteractionKind.CLIENT_TOOL,
            payload=client_tool_payload(channel, et, params=params),
        )
        req = registry.get(rid)
        assert req is not None
        event = build_client_tool_required(req)
        assert event is not None
        assert event.type == expected_type
        assert event.payload["request_id"] == rid
        assert event.payload["conversation_id"] == CONV
        assert not fut.done()
        registry.discard(rid)


async def test_attach_resends_open_client_tool(monkeypatch):
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    registry = default_interaction_registry()
    # Isolate: drop any leftover pending from other tests on this process registry.
    for leftover in list(registry.list_pending(CONV)):
        registry.discard(leftover.id)

    sink = EventSink(conversation_id=CONV)
    sink.emit(content_delta("Hi"))
    sink.detach()

    fut = registry.create(
        "req-open",
        CONV,
        kind=InteractionKind.CLIENT_TOOL,
        payload=client_tool_payload(
            CHANNEL_WORKSPACE,
            EventType.WORKSPACE_OP_REQUIRED.value,
            params={"root_id": "root-1", "op": "read", "args": {"path": "x.txt"}},
        ),
    )
    assert not fut.done()

    gen = sse._attach_generator(sink)
    frames: list[str] = []
    try:
        for _ in range(8):
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            frames.append(chunk)
            if "workspace_op_required" in chunk:
                break
        else:
            pytest.fail("workspace_op_required not re-emitted on attach")
    finally:
        await gen.aclose()
        registry.discard("req-open")

    types = _parse_sse_types(frames)
    assert EventType.CONTENT_DELTA.value in types
    assert EventType.WORKSPACE_OP_REQUIRED.value in types
    # Re-hang lands after history replay.
    assert types.index(EventType.CONTENT_DELTA.value) < types.index(
        EventType.WORKSPACE_OP_REQUIRED.value
    )
    payloads = _parse_sse_payloads(frames)
    op = next(p for p in payloads if p["type"] == EventType.WORKSPACE_OP_REQUIRED.value)
    assert op["payload"]["request_id"] == "req-open"
    assert op["payload"]["root_id"] == "root-1"
    assert op["payload"]["op"] == "read"
    assert op["payload"]["args"] == {"path": "x.txt"}


async def test_attach_skips_discarded_client_tool(monkeypatch):
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    registry = default_interaction_registry()
    for leftover in list(registry.list_pending(CONV)):
        registry.discard(leftover.id)

    sink = EventSink(conversation_id=CONV)
    sink.emit(content_delta("Hi"))
    sink.detach()

    registry.create(
        "req-gone",
        CONV,
        kind=InteractionKind.CLIENT_TOOL,
        payload=client_tool_payload(
            CHANNEL_HOST,
            EventType.HOST_OP_REQUIRED.value,
            params={"op": "host_ping", "args": {}},
        ),
    )
    registry.discard("req-gone")
    assert registry.list_pending(CONV) == []

    gen = sse._attach_generator(sink)
    frames: list[str] = []
    try:
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        frames.append(chunk)
        # Next frame would be live tail / ping — give one more pull briefly.
        with contextlib.suppress(TimeoutError):
            frames.append(await asyncio.wait_for(gen.__anext__(), timeout=0.05))
    finally:
        await gen.aclose()

    joined = "".join(frames)
    assert "host_op_required" not in joined
    assert "content_delta" in joined


async def test_build_skips_done_future():
    registry = InteractionRegistry()
    fut = registry.create(
        "req-done",
        CONV,
        kind=InteractionKind.CLIENT_TOOL,
        payload=client_tool_payload(
            CHANNEL_NOTIFY,
            EventType.DESKTOP_NOTIFY_REQUIRED.value,
            params={"title": "t", "body": ""},
        ),
    )
    fut.set_result({"ok": True, "value": {}})
    req = registry.get("req-done")
    assert req is not None
    assert build_client_tool_required(req) is None
    registry.discard("req-done")
