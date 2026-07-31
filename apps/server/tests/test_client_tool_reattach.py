"""CLIENT_TOOL + hot-path ``*_required`` re-hang on SSE attach (refresh while open)."""

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
from agentcore.runtime.events.hot_interaction_reattach import (
    build_hot_interaction_required,
    registry_hot_pending,
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


def _clear_pending(registry: InteractionRegistry, conversation_id: str = CONV) -> None:
    for leftover in list(registry.list_pending(conversation_id)):
        registry.discard(leftover.id)


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
    _clear_pending(registry)

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
    _clear_pending(registry)

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


# --- Hot-path approval / escalation re-hang -----------------------------------


async def test_build_hot_approval_fills_wire_ids():
    registry = InteractionRegistry()
    registry.create(
        "call-42",
        CONV,
        kind=InteractionKind.APPROVAL,
        payload={
            "tool_call_id": "call-42",
            "tool_name": "file_write",
            "arguments": {"path": "a.txt"},
        },
    )
    req = registry.get("call-42")
    assert req is not None
    event = build_hot_interaction_required(req)
    assert event is not None
    assert event.type is EventType.APPROVAL_REQUIRED
    assert event.payload == {
        "approval_id": "call-42",
        "conversation_id": CONV,
        "tool_call_id": "call-42",
        "tool_name": "file_write",
        "arguments": {"path": "a.txt"},
    }
    registry.discard("call-42")


async def test_build_hot_skips_done_and_ceo_escalation():
    registry = InteractionRegistry()
    fut = registry.create(
        "appr-done",
        CONV,
        kind=InteractionKind.APPROVAL,
        payload={"tool_call_id": "appr-done", "tool_name": "mkdir", "arguments": {}},
    )
    fut.set_result("approve")
    done_req = registry.get("appr-done")
    assert done_req is not None
    assert build_hot_interaction_required(done_req) is None

    registry.create(
        "esc-ceo",
        CONV,
        kind=InteractionKind.ESCALATION,
        payload={
            "escalation_id": "esc-ceo",
            "run_id": "r1",
            "agent_id": "w1",
            "question": "q",
            "assumption": "a",
            "awaiting": "ceo",
        },
    )
    ceo_req = registry.get("esc-ceo")
    assert ceo_req is not None
    assert build_hot_interaction_required(ceo_req) is None

    registry.create(
        "esc-user",
        CONV,
        kind=InteractionKind.ESCALATION,
        payload={
            "escalation_id": "esc-user",
            "run_id": "r1",
            "agent_id": "w1",
            "question": "pick?",
            "assumption": "default",
            "awaiting": "user",
        },
    )
    user_req = registry.get("esc-user")
    assert user_req is not None
    esc = build_hot_interaction_required(user_req)
    assert esc is not None
    assert esc.type is EventType.ESCALATION_REQUIRED
    assert esc.payload["escalation_id"] == "esc-user"
    assert esc.payload["awaiting"] == "user"

    registry.discard("appr-done")
    registry.discard("esc-ceo")
    registry.discard("esc-user")


async def test_attach_resends_open_approval(monkeypatch):
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    registry = default_interaction_registry()
    _clear_pending(registry)

    sink = EventSink(conversation_id=CONV)
    sink.emit(content_delta("Hi"))
    sink.detach()

    registry.create(
        "appr-open",
        CONV,
        kind=InteractionKind.APPROVAL,
        payload={
            "tool_call_id": "appr-open",
            "tool_name": "file_write",
            "arguments": {"path": "x.txt"},
        },
    )

    gen = sse._attach_generator(sink)
    frames: list[str] = []
    try:
        for _ in range(8):
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            frames.append(chunk)
            if "approval_required" in chunk:
                break
        else:
            pytest.fail("approval_required not re-emitted on attach")
    finally:
        await gen.aclose()
        registry.discard("appr-open")

    types = _parse_sse_types(frames)
    assert EventType.CONTENT_DELTA.value in types
    assert EventType.APPROVAL_REQUIRED.value in types
    assert types.index(EventType.CONTENT_DELTA.value) < types.index(
        EventType.APPROVAL_REQUIRED.value
    )
    payloads = _parse_sse_payloads(frames)
    card = next(p for p in payloads if p["type"] == EventType.APPROVAL_REQUIRED.value)
    assert card["payload"]["approval_id"] == "appr-open"
    assert card["payload"]["conversation_id"] == CONV
    assert card["payload"]["tool_name"] == "file_write"


async def test_attach_skips_discarded_approval(monkeypatch):
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    registry = default_interaction_registry()
    _clear_pending(registry)

    sink = EventSink(conversation_id=CONV)
    sink.emit(content_delta("Hi"))
    sink.detach()

    registry.create(
        "appr-gone",
        CONV,
        kind=InteractionKind.APPROVAL,
        payload={
            "tool_call_id": "appr-gone",
            "tool_name": "code_execute",
            "arguments": {},
        },
    )
    registry.discard("appr-gone")

    gen = sse._attach_generator(sink)
    frames: list[str] = []
    try:
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        frames.append(chunk)
        with contextlib.suppress(TimeoutError):
            frames.append(await asyncio.wait_for(gen.__anext__(), timeout=0.05))
    finally:
        await gen.aclose()

    joined = "".join(frames)
    assert "approval_required" not in joined
    assert "content_delta" in joined


async def test_registry_hot_pending_recovery_payload():
    """Registry-only open approval enters recovery summaries with wire fields."""
    registry = default_interaction_registry()
    _clear_pending(registry)
    registry.create(
        "appr-rec",
        CONV,
        kind=InteractionKind.APPROVAL,
        payload={
            "tool_call_id": "appr-rec",
            "tool_name": "file_write",
            "arguments": {"path": "/tmp/x"},
        },
    )
    try:
        pending = registry_hot_pending(CONV, message_id="msg-live")
        assert len(pending) == 1
        assert pending[0].kind == "approval"
        assert pending[0].id == "appr-rec"
        assert pending[0].message_id == "msg-live"
        assert pending[0].payload["approval_id"] == "appr-rec"
        assert pending[0].payload["conversation_id"] == CONV
        assert pending[0].payload["tool_name"] == "file_write"
    finally:
        registry.discard("appr-rec")
