"""ask_user 非阻塞发问 (Cursor 式 CEO 层增强): surface + proceed, never suspend.

The blocking ask_user (suspend+resume) lives in test_resume_ask_user; this pins the
NON-blocking branch the model opts into via ``blocking=false``. It must NOT touch the
suspend bridge (no freeze), must require a stated default (else steer back to blocking),
stream a non-gating ``content_delta`` notice (NOT a checkpoint card), and feed the CEO a
``CONTINUE`` result that orders it to keep working on its default.
"""

from pathlib import Path

from agentcore.core.types import ToolEffect
from agentcore.runtime.events import EventSink, EventType, SSEEvent
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c1",
    )


def _tool() -> AskUserTool:
    return AskUserTool(
        sink=EventSink(),
        conversation_id="c1",
        timeout_seconds=1.0,
    )


def _drain(sink: EventSink) -> list[SSEEvent]:
    out: list[SSEEvent] = []
    while not sink._queue.empty():  # noqa: SLF001 - test-only inspection
        out.append(sink._queue.get_nowait())
    return out


def _posted(events: list[SSEEvent]) -> SSEEvent:
    return next(e for e in events if e.type is EventType.QUESTION_POSTED)


async def test_nonblocking_returns_continue_and_does_not_suspend():
    tool = _tool()
    res = await tool.execute(
        {
            "message": "我先按响应式单页来做",
            "questions": [{"prompt": "要不要双语?", "options": ["要", "不要"], "default": "不要"}],
            "blocking": False,
        },
        _ctx(),
    )
    # CONTINUE (non-terminal): the CEO keeps working; it neither ends nor awaits the turn.
    assert res.success is True
    assert res.effect is ToolEffect.CONTINUE
    assert res.is_terminal is False
    assert "不要等待" in res.output
    # The question surfaced as a non-gating question_posted card — NOT a checkpoint.
    events = _drain(tool.sink)
    assert not any(e.type is EventType.CHECKPOINT_REQUIRED for e in events)
    posted = _posted(events)
    assert posted.payload["question"] == "我先按响应式单页来做"
    q0 = posted.payload["questions"][0]
    assert q0["default"] == "不要" and any(o["label"] == "要" for o in q0["options"])
    assert posted.payload["ask_id"]  # keyed for dedupe


async def test_nonblocking_accepts_assumption_as_the_fallback():
    tool = _tool()
    res = await tool.execute(
        {
            "message": "继续推进，技术细节我先定了",
            "assumptions": [{"label": "部署", "value": "纯静态"}],
            "blocking": False,
        },
        _ctx(),
    )
    assert res.success is True and res.effect is ToolEffect.CONTINUE
    assumptions = _posted(_drain(tool.sink)).payload["assumptions"]
    assert assumptions[0]["label"] == "部署" and assumptions[0]["value"] == "纯静态"


async def test_nonblocking_without_any_default_is_rejected():
    # A non-blocking ask with no assumption AND no question default would silently
    # guess — refuse it and steer the model to blocking. Nothing is surfaced.
    tool = _tool()
    res = await tool.execute(
        {
            "message": "A 还是 B?",
            "questions": [{"prompt": "A 还是 B?", "options": ["A", "B"]}],
            "blocking": False,
        },
        _ctx(),
    )
    assert res.success is False
    assert "blocking=true" in (res.error or "")
    assert _drain(tool.sink) == []  # nothing surfaced on the rejected path


async def test_blocking_defaults_true_and_fails_without_durable_frame():
    # D11：无 transcript/saver 时不再走窄兜底 suspend，显式失败。
    # 带 questions 以越过 kickoff 提案体硬闸，专测持久化失败路径。
    tool = _tool()
    res = await tool.execute(
        {
            "message": "A 还是 B?",
            "questions": [{"prompt": "A 还是 B?", "options": ["A", "B"]}],
        },
        _ctx(),
    )
    assert res.success is False
    assert "持久化" in (res.output or "")


async def test_empty_message_rejected_before_blocking_branch():
    tool = _tool()
    res = await tool.execute({"message": "  ", "blocking": False}, _ctx())
    assert res.success is False
    assert "message" in (res.error or "")
    assert _drain(tool.sink) == []
