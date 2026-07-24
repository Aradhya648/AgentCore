"""Tests for the whiteboard op channel + tool (AI协作白板.md §六 M2).

Covers the server half of "the AI draws on your board" without an actual desktop:

  * ``BoardChannel`` — suspends an op batch on the interaction bridge, emits a
    ``board_op_required`` event carrying the board id + ops, and returns the desktop's
    value (or raises ``BoardOpError`` on failure / malformed envelope / timeout).
  * ``BoardOpsTool`` — refuses to run off a board, validates the op batch, and maps the
    channel's result / error into a ``ToolResult`` the model can act on.

A fake "desktop" drives each round trip: it reads the emitted event off the sink to
learn the ``request_id``, then settles the registry with a canned result.
"""

import asyncio

import pytest

from agentcore.board.channel import BoardChannel, BoardOpError
from agentcore.runtime.events import EventSink, EventType, SSEEvent
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.tools.builtin.board_ops import BoardOpsTool
from agentcore.tools.protocol import ToolContext

pytestmark = pytest.mark.anyio

CONV = "conv-1"
BOARD = "board-1"


def _make(timeout: float = 5.0) -> tuple[BoardChannel, InteractionRegistry, EventSink]:
    sink = EventSink()
    registry = InteractionRegistry()
    channel = BoardChannel(
        sink=sink,
        conversation_id=CONV,
        board_id=BOARD,
        registry=registry,
        timeout_seconds=timeout,
    )
    return channel, registry, sink


def _ctx(channel: BoardChannel | None) -> ToolContext:
    return ToolContext(
        execution_id="exec-1",
        run_id="run-1",
        agent_id="agent-1",
        backend=None,  # type: ignore[arg-type] - board_ops never touches the FS backend
        user_id="user-1",
        conversation_id=CONV,
        board_channel=channel,
    )


async def _await_request(sink: EventSink) -> SSEEvent:
    """Return the op event the channel just emitted (yielding so the op runs)."""
    for _ in range(2000):
        if not sink._queue.empty():  # noqa: SLF001 - test-only inspection
            return sink._queue.get_nowait()
        await asyncio.sleep(0)
    raise AssertionError("no board_op_required event emitted")


async def _round_trip(coro, sink: EventSink, registry: InteractionRegistry, response: dict):
    """Drive one batch: start it, answer it as the desktop would, return (result, event)."""
    task = asyncio.create_task(coro)
    event = await _await_request(sink)
    assert registry.resolve(event.payload["request_id"], response, conversation_id=CONV)
    return await task, event


# --- BoardChannel transport --------------------------------------------------


async def test_ops_round_trip_through_channel():
    channel, registry, sink = _make()
    ops = [{"op": "add_node", "ref": "a", "text": "Hi"}]
    value = {"applied": 1, "created": ["el-1"], "version": 2}
    result, event = await _round_trip(
        channel.request(ops, summary="加一个便利贴"),
        sink,
        registry,
        {"ok": True, "value": value},
    )
    assert result == value
    assert event.type == EventType.BOARD_OP_REQUIRED
    assert event.payload["board_id"] == BOARD
    assert event.payload["conversation_id"] == CONV
    assert event.payload["ops"] == ops
    assert event.payload["summary"] == "加一个便利贴"


async def test_failed_envelope_raises_board_error():
    channel, registry, sink = _make()
    with pytest.raises(BoardOpError, match="boom"):
        await _round_trip(
            channel.request([{"op": "delete", "id": "x"}]),
            sink,
            registry,
            {"ok": False, "error": {"detail": "boom"}},
        )


async def test_malformed_envelope_raises_board_error():
    channel, registry, sink = _make()
    with pytest.raises(BoardOpError):
        await _round_trip(
            channel.request([{"op": "add_node"}]), sink, registry, {"unexpected": True}
        )


async def test_timeout_raises_board_error():
    channel, _registry, _sink = _make(timeout=0.05)
    # No desktop answers, so the batch times out and surfaces as a BoardOpError.
    with pytest.raises(BoardOpError):
        await channel.request([{"op": "add_node", "text": "never applied"}])


# --- BoardOpsTool guards / validation / mapping ------------------------------


async def test_tool_off_board_errors():
    result = await BoardOpsTool().execute({"ops": [{"op": "add_node"}]}, _ctx(None))
    assert not result.success
    assert "白板会话" in (result.error or "")


async def test_tool_empty_ops_errors():
    channel, _registry, _sink = _make()
    result = await BoardOpsTool().execute({"ops": []}, _ctx(channel))
    assert not result.success
    assert "ops" in (result.error or "")


@pytest.mark.parametrize(
    "ops",
    [
        [{"op": "frobnicate"}],  # unknown verb
        [{"op": "connect", "from": "a"}],  # missing endpoint
        [{"op": "move"}],  # no target id/ref
        [{"op": "group"}],  # no members
    ],
)
async def test_tool_validation_rejects_bad_ops(ops):
    channel, _registry, _sink = _make()
    result = await BoardOpsTool().execute({"ops": ops}, _ctx(channel))
    assert not result.success and result.error


async def test_tool_applies_and_formats_result():
    channel, registry, sink = _make()
    tool = BoardOpsTool()
    task = asyncio.create_task(
        tool.execute(
            {"ops": [{"op": "add_node", "ref": "a", "text": "Hi"}], "summary": "s"},
            _ctx(channel),
        )
    )
    event = await _await_request(sink)
    assert registry.resolve(
        event.payload["request_id"],
        {"ok": True, "value": {"applied": 1, "created": ["el-1"], "version": 2}},
        conversation_id=CONV,
    )
    result = await task
    assert result.success
    assert "已在白板应用" in result.output


async def test_tool_maps_board_error_to_failed_result():
    channel, _registry, _sink = _make(timeout=0.05)
    # No desktop answers → channel raises BoardOpError → tool returns a failed result.
    result = await BoardOpsTool().execute(
        {"ops": [{"op": "add_node", "text": "x"}]}, _ctx(channel)
    )
    assert not result.success
    assert "未应用" in (result.error or "")
