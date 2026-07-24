"""Tests for the whiteboard read channel + tool (AI协作白板.md §九).

Covers the server half of "the AI 看懂 your hand-drawn / screenshot brief" without an
actual desktop or vision model:

  * ``BoardChannel.read`` — suspends a rasterize request on the interaction bridge, emits a
    ``board_read_required`` event carrying the board id + element ids, and returns the
    desktop's value (or raises ``BoardReadError`` on failure / malformed envelope / timeout).
  * ``BoardReadTool`` — refuses to run off a board, refuses with no vision provider wired
    (the current skeleton state), validates the ids, and maps the channel result + vision
    reader output (or errors) into a ``ToolResult`` the model can act on.

A fake "desktop" drives each round trip (reads the emitted event off the sink for the
``request_id``, then settles the registry with a canned PNG); a fake ``VisionReader`` stands
in for the (unwired) vision model.
"""

import asyncio

import pytest

from agentcore.board.channel import BoardChannel, BoardReadError
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.costing import ROLE_VISION, RunCost
from agentcore.runtime.events import EventSink, EventType, SSEEvent
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.tools.builtin.board_read import BoardReadTool
from agentcore.tools.protocol import ToolContext
from agentcore.vision.protocol import VisionReading

pytestmark = pytest.mark.anyio

CONV = "conv-1"
BOARD = "board-1"
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


class _FakeReader:
    """A stub VisionReader: records its calls, returns a canned VisionReading.

    ``usage`` / ``model`` default to a billable reading (so the cost-sink path is the
    common case under test); pass ``usage=TokenUsage()`` + ``model=""`` for a stub that
    bills nothing.
    """

    def __init__(
        self,
        text: str = "登录流程草图：用户 → 登录页 → 首页",
        *,
        usage: TokenUsage | None = None,
        model: str = "qwen-vl-max",
    ) -> None:
        self.text = text
        self.usage = usage if usage is not None else TokenUsage(input_tokens=900, output_tokens=30)
        self.model = model
        self.calls: list[tuple[str, str]] = []

    async def read(self, png_base64: str, prompt: str) -> VisionReading:
        self.calls.append((png_base64, prompt))
        return VisionReading(text=self.text, usage=self.usage, model=self.model)


class _BoomReader:
    """A VisionReader that always fails — exercises the tool's reader-error mapping."""

    async def read(self, png_base64: str, prompt: str) -> VisionReading:
        raise RuntimeError("vision provider down")


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


def _ctx(
    channel: BoardChannel | None,
    reader: object | None = None,
    *,
    cost_sink: list[RunCost] | None = None,
) -> ToolContext:
    return ToolContext(
        execution_id="exec-1",
        run_id="run-1",
        agent_id="agent-1",
        backend=None,  # type: ignore[arg-type] - board_read never touches the FS backend
        user_id="user-1",
        conversation_id=CONV,
        board_channel=channel,
        vision_reader=reader,  # type: ignore[arg-type] - duck-typed stub
        cost_sink=cost_sink,
    )


async def _await_request(sink: EventSink) -> SSEEvent:
    """Return the read event the channel just emitted (yielding so the read runs)."""
    for _ in range(2000):
        if not sink._queue.empty():  # noqa: SLF001 - test-only inspection
            return sink._queue.get_nowait()
        await asyncio.sleep(0)
    raise AssertionError("no board_read_required event emitted")


async def _round_trip(coro, sink: EventSink, registry: InteractionRegistry, response: dict):
    """Drive one read: start it, answer it as the desktop would, return (result, event)."""
    task = asyncio.create_task(coro)
    event = await _await_request(sink)
    assert registry.resolve(event.payload["request_id"], response, conversation_id=CONV)
    return await task, event


# --- BoardChannel.read transport ---------------------------------------------


async def test_read_round_trip_through_channel():
    channel, registry, sink = _make()
    ids = ["el-1", "el-2"]
    value = {"pngBase64": PNG, "w": 320, "h": 200}
    result, event = await _round_trip(
        channel.read(ids),
        sink,
        registry,
        {"ok": True, "value": value},
    )
    assert result == value
    assert event.type == EventType.BOARD_READ_REQUIRED
    assert event.payload["board_id"] == BOARD
    assert event.payload["conversation_id"] == CONV
    assert event.payload["ids"] == ids


async def test_read_failed_envelope_raises_board_read_error():
    channel, registry, sink = _make()
    with pytest.raises(BoardReadError, match="boom"):
        await _round_trip(
            channel.read(["el-1"]),
            sink,
            registry,
            {"ok": False, "error": {"detail": "boom"}},
        )


async def test_read_malformed_envelope_raises_board_read_error():
    channel, registry, sink = _make()
    with pytest.raises(BoardReadError):
        await _round_trip(channel.read(["el-1"]), sink, registry, {"unexpected": True})


async def test_read_timeout_raises_board_read_error():
    channel, _registry, _sink = _make(timeout=0.05)
    with pytest.raises(BoardReadError):
        await channel.read(["el-1"])


# --- BoardReadTool guards / validation / mapping -----------------------------


async def test_tool_off_board_errors():
    result = await BoardReadTool().execute({"ids": ["el-1"]}, _ctx(None, _FakeReader()))
    assert not result.success
    assert "白板会话" in (result.error or "")


async def test_tool_no_vision_reader_errors():
    channel, _registry, _sink = _make()
    result = await BoardReadTool().execute({"ids": ["el-1"]}, _ctx(channel, None))
    assert not result.success
    assert "未配置" in (result.error or "")


@pytest.mark.parametrize("ids", [[], "not-a-list", [""], [123]])
async def test_tool_rejects_bad_ids(ids):
    channel, _registry, _sink = _make()
    result = await BoardReadTool().execute({"ids": ids}, _ctx(channel, _FakeReader()))
    assert not result.success and result.error


async def test_tool_reads_and_returns_vision_text():
    channel, registry, sink = _make()
    reader = _FakeReader()
    tool = BoardReadTool()
    task = asyncio.create_task(tool.execute({"ids": ["el-1"]}, _ctx(channel, reader)))
    event = await _await_request(sink)
    assert registry.resolve(
        event.payload["request_id"],
        {"ok": True, "value": {"pngBase64": PNG, "w": 100, "h": 80}},
        conversation_id=CONV,
    )
    result = await task
    assert result.success
    assert result.output == reader.text
    # The reader saw the desktop's PNG and the brief framing prompt.
    assert reader.calls and reader.calls[0][0] == PNG
    assert "brief" in reader.calls[0][1]


async def test_tool_empty_png_value_errors():
    channel, registry, sink = _make()
    tool = BoardReadTool()
    task = asyncio.create_task(tool.execute({"ids": ["el-1"]}, _ctx(channel, _FakeReader())))
    event = await _await_request(sink)
    assert registry.resolve(
        event.payload["request_id"],
        {"ok": True, "value": {"w": 100, "h": 80}},
        conversation_id=CONV,
    )
    result = await task
    assert not result.success
    assert "为空" in (result.error or "")


async def test_tool_maps_board_read_error_to_failed_result():
    channel, _registry, _sink = _make(timeout=0.05)
    # No desktop answers → channel raises BoardReadError → tool returns a failed result.
    result = await BoardReadTool().execute({"ids": ["el-1"]}, _ctx(channel, _FakeReader()))
    assert not result.success
    assert "未完成" in (result.error or "")


async def test_tool_maps_vision_failure_to_failed_result():
    channel, registry, sink = _make()
    tool = BoardReadTool()
    task = asyncio.create_task(tool.execute({"ids": ["el-1"]}, _ctx(channel, _BoomReader())))
    event = await _await_request(sink)
    assert registry.resolve(
        event.payload["request_id"],
        {"ok": True, "value": {"pngBase64": PNG, "w": 100, "h": 80}},
        conversation_id=CONV,
    )
    result = await task
    assert not result.success
    assert "解读失败" in (result.error or "")


# --- 读图入账 (AI协作白板.md §九.4 Gap ②) ------------------------------------


async def _read_with_sink(reader: object, sink_list: list[RunCost] | None) -> None:
    """Drive one successful board_read with the given reader + cost sink."""
    channel, registry, sink = _make()
    tool = BoardReadTool()
    task = asyncio.create_task(
        tool.execute({"ids": ["el-1"]}, _ctx(channel, reader, cost_sink=sink_list))
    )
    event = await _await_request(sink)
    assert registry.resolve(
        event.payload["request_id"],
        {"ok": True, "value": {"pngBase64": PNG, "w": 100, "h": 80}},
        conversation_id=CONV,
    )
    result = await task
    assert result.success


async def test_tool_bills_vision_subcall_into_cost_sink():
    sink_rows: list[RunCost] = []
    await _read_with_sink(_FakeReader(), sink_rows)
    assert len(sink_rows) == 1
    row = sink_rows[0]
    # One priced role=vision row, parented to the calling run, with its own vis_ id and
    # the vision model's token counts — its own line on the team payroll, never folded.
    assert row.role == ROLE_VISION
    assert row.model == "qwen-vl-max"
    assert row.parent_run_id == "run-1"
    assert row.run_id.startswith("vis_")
    assert row.rounds == 1
    assert row.tokens["input"] == 900
    assert row.tokens["output"] == 30
    # qwen-vl-max input billed as a miss (no cache split): 900×$0.80/1M + 30×$3.20/1M.
    assert row.cost_total_nano == 900 * 800 + 30 * 3200


async def test_tool_no_sink_still_succeeds_without_billing():
    # No cost sink (tests / no board): a read still succeeds, accounting is simply skipped.
    await _read_with_sink(_FakeReader(), None)


async def test_tool_stub_reader_with_no_usage_bills_nothing():
    sink_rows: list[RunCost] = []
    # A reader that signals no usage / model (a pure stub) leaves the ledger untouched.
    await _read_with_sink(_FakeReader(usage=TokenUsage(), model=""), sink_rows)
    assert sink_rows == []
