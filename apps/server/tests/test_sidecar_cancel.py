"""Sidecar cancel ≡ cloud /stop: cascade coordination + emit message_end(cancelled)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentcore.runtime.coordination.session import (
    CoordinationSession,
    active_coordination,
    clear_active_coordination,
    release_turn_coordination,
    set_active_coordination,
)
from agentcore.runtime.events import EventSink, EventType, FinishReason
from agentcore.sidecar.server import SidecarServer
from agentcore.sidecar.server_pkg.turns import (
    _emit_cancel_end_if_cancelling,
    _emit_user_stop_message_end,
)


def _recorder() -> tuple[list[dict[str, Any]], Any]:
    lines: list[dict[str, Any]] = []

    async def write_line(line: str) -> None:
        lines.append(json.loads(line))

    return lines, write_line


def _req(request_id: int, method: str, params: dict[str, Any]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    )


@pytest.fixture(autouse=True)
def _clear_coord():
    clear_active_coordination()
    yield
    clear_active_coordination()


async def test_sidecar_cancel_cascades_user_stop_not_detach():
    """cancel marks user_stopped + cancels drive — release clears (no detach continue)."""
    lines, write_line = _recorder()
    server = SidecarServer(write_line)
    server._initialized = True

    conversation_id = "conv-sidecar-stop"
    turn_id = "turn-1"
    session = CoordinationSession(
        execution_id="e-sidecar-stop",
        total_workers=1,
        conversation_id=conversation_id,
    )
    session._running_workers["w1"] = "研究员"

    async def _hang() -> None:
        await asyncio.Event().wait()

    session.drive_task = asyncio.create_task(_hang())
    set_active_coordination(session)

    async def _turn_hang() -> None:
        await asyncio.Event().wait()

    turn_task = asyncio.create_task(_turn_hang())
    server._register_turn(turn_id, turn_task, conversation_id=conversation_id)

    await server.handle_line(
        _req(99, "cancel", {"turnId": turn_id, "conversationId": conversation_id})
    )

    assert session.user_stopped is True
    assert "w1" in session.cancel_ids
    await asyncio.sleep(0)
    assert turn_task.cancelled() or turn_task.done()
    assert session.drive_task.cancelled() or session.drive_task.done()

    # Same as cloud /stop: release clears instead of detach-and-continue.
    release_turn_coordination("e-sidecar-stop")
    assert active_coordination("e-sidecar-stop") is None

    replies = [m for m in lines if m.get("id") == 99]
    assert replies and replies[0].get("result", {}).get("cancelled") is True

    if not turn_task.done():
        turn_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn_task


async def test_sidecar_cancel_resolves_conversation_from_turn_map():
    """conversationId may be omitted when startTurn registered the mapping."""
    _lines, write_line = _recorder()
    server = SidecarServer(write_line)
    server._initialized = True

    conversation_id = "conv-mapped"
    turn_id = "turn-map"
    session = CoordinationSession(
        execution_id="e-map", total_workers=1, conversation_id=conversation_id
    )

    async def _hang() -> None:
        await asyncio.Event().wait()

    session.drive_task = asyncio.create_task(_hang())
    set_active_coordination(session)

    turn_task = asyncio.create_task(_hang())
    server._register_turn(turn_id, turn_task, conversation_id=conversation_id)

    await server.handle_line(_req(7, "cancel", {"turnId": turn_id}))

    assert session.user_stopped is True

    if not turn_task.done():
        turn_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn_task
    release_turn_coordination("e-map")
    assert active_coordination("e-map") is None


async def _drain_until_message_end(sink: EventSink) -> dict:
    """Pull from the live queue until message_end (MESSAGE_END is history-skipped)."""
    while True:
        ev = await asyncio.wait_for(sink.get(), timeout=1.0)
        assert ev is not None
        if ev.type == EventType.MESSAGE_END:
            return dict(ev.payload)


def test_emit_user_stop_message_end_sets_cancelled_finish_reason():
    sink = EventSink()
    _emit_user_stop_message_end(sink)
    assert not sink._closed
    assert sink._stream_finish_reason == FinishReason.CANCELLED.value


async def test_emit_cancel_end_if_cancelling_only_when_task_cancelling():
    sink = EventSink()
    # Not cancelling → no-op
    _emit_cancel_end_if_cancelling(sink)
    assert sink._stream_finish_reason is None

    async def _body() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            _emit_cancel_end_if_cancelling(sink)

    task = asyncio.create_task(_body())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sink._stream_finish_reason == FinishReason.CANCELLED.value
    payload = await _drain_until_message_end(sink)
    assert payload["finish_reason"] == FinishReason.CANCELLED


async def test_close_user_stop_turn_emits_message_end_even_when_persist_skipped(monkeypatch):
    """Cloud isomorphic C: live confirmation even when durable salvage gates skip."""
    from agentcore.conversation import turn_persistence

    monkeypatch.setattr(
        turn_persistence.settings, "incomplete_turn_persist_enabled", False
    )
    sink = EventSink()
    closed = await turn_persistence.close_user_stop_turn(
        sink=sink,
        conversation_id="c1",
        trace_id="t1",
        message_id="m1",
    )
    assert closed is False
    assert sink._stream_finish_reason == FinishReason.CANCELLED.value
    payload = await _drain_until_message_end(sink)
    assert payload["finish_reason"] == FinishReason.CANCELLED
