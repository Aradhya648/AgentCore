"""Tests for parallel tool execution and per-tool exception firewall (audit/05 P2-1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from agentcore.core.errors import SandboxError
from agentcore.core.types import ToolCategory, ToolEffect
from agentcore.llm.provider.protocol import ToolCall, ToolCallFunction
from agentcore.runtime.engine.tool_exec import execute_tools
from agentcore.runtime.events import EventSink, EventType
from agentcore.tools.builtin.code_execute import CodeExecuteTool
from agentcore.tools.builtin.test_run import TestRunTool
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(backend=None) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=backend
        or ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


def _call(tool_id: str, name: str, args: str = "{}") -> ToolCall:
    return ToolCall(id=tool_id, function=ToolCallFunction(name=name, arguments=args))


class _OkTool:
    def __init__(self, name: str = "ok", *, output: str = "done") -> None:
        self._name = name
        self._output = output
        self.executed = False

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.SEARCH,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.executed = True
        return ToolResult(tool_call_id="", success=True, output=self._output)


class _CrashTool:
    def __init__(self, name: str = "crash") -> None:
        self._name = name
        self.executed = False

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.SEARCH,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.executed = True
        raise SandboxError("sandbox blew up")


class _SuspendTool:
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="ask",
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.INTERACTION,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            tool_call_id="",
            success=True,
            output="waiting",
            effect=ToolEffect.SUSPEND,
        )


class _HandoffTool:
    def __init__(self, name: str = "handoff") -> None:
        self._name = name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.ORCHESTRATION,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            tool_call_id="",
            success=True,
            output="done",
            effect=ToolEffect.HANDOFF,
            final_text="handoff answer",
        )


class _ContractRejectTool:
    """A tool that returns a self-correctable参数契约拒绝 (web_search A3 shape)."""

    def __init__(self, name: str = "web_search") -> None:
        self._name = name
        self.executed = False

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.RESEARCH,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.executed = True
        return ToolResult(
            tool_call_id="",
            success=False,
            output="",
            error="查询词过多（未加引号部分 8 个词，上限 6）。请改用 2–4 个核心词重试。",
            contract_failure=True,
        )


class _FakeBackend:
    def __init__(self, *, raise_sandbox: bool = False) -> None:
        self._raise_sandbox = raise_sandbox
        self.requests: list[ExecutionRequest] = []

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        if self._raise_sandbox:
            raise SandboxError("代码执行环境启动失败：interpreter missing")
        return ExecutionResult(success=True, stdout="ok\n", stderr="", exit_code=0, duration_ms=1)

    async def read(self, path: str) -> bytes:
        raise FileNotFoundError(path)

    async def index_files(self, *, cap: int = 50, order: str = "recent"):
        return [], 0


@pytest.fixture
def registry() -> tuple[ToolRegistry, _OkTool]:
    ok_b = _OkTool("ok_b", output="beta")
    reg = ToolRegistry()
    reg.register(_OkTool("ok_a", output="alpha"))
    reg.register(ok_b)
    reg.register(_CrashTool())
    reg.register(_SuspendTool())
    return reg, ok_b


async def test_parallel_crash_does_not_cancel_sibling(registry: tuple[ToolRegistry, _OkTool]):
    reg, ok_b = registry
    sink = EventSink()
    messages, terminal, attempts = await execute_tools(
        [_call("c1", "crash"), _call("c2", "ok_b")],
        reg,
        _ctx(),
        sink,
        run_id="r1",
    )

    assert ok_b.executed is True
    assert terminal is None
    assert len(messages) == 2
    assert len(attempts) == 2
    assert attempts[0].success is False
    assert attempts[1].success is True
    crash_msg = next(m for m in messages if m.tool_call_id == "c1")
    ok_msg = next(m for m in messages if m.tool_call_id == "c2")
    assert "内部错误" in (crash_msg.content or "")
    assert ok_msg.content == "beta"


async def test_crash_emits_failed_tool_use_end(registry: tuple[ToolRegistry, _OkTool]):
    reg, _ok_b = registry
    sink = EventSink()
    await execute_tools([_call("c1", "crash")], reg, _ctx(), sink, run_id="r1")

    ends = [e for e in sink._history if e.type == EventType.TOOL_USE_END]  # noqa: SLF001
    assert len(ends) == 1
    assert ends[0].payload["status"] == "error"
    assert "内部错误" in (ends[0].payload.get("result") or "")


async def test_crash_message_carries_exception_type(registry: tuple[ToolRegistry, _OkTool]):
    """空 str(e) 异常（如裸 NotImplementedError）也必须给模型可读的失败原因。"""

    class _EmptyStrCrashTool(_CrashTool):
        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            raise NotImplementedError

    reg, _ok_b = registry
    reg.register(_EmptyStrCrashTool("crash_empty"))
    sink = EventSink()
    messages, _terminal, _attempts = await execute_tools(
        [_call("c1", "crash_empty"), _call("c2", "crash")],
        reg,
        _ctx(),
        sink,
        run_id="r1",
    )

    empty_msg = next(m for m in messages if m.tool_call_id == "c1")
    assert "NotImplementedError" in (empty_msg.content or "")
    assert "：。" not in (empty_msg.content or "")
    # 非空 str(e) 同样带类型名前缀，原文保留。
    crash_msg = next(m for m in messages if m.tool_call_id == "c2")
    assert "SandboxError: sandbox blew up" in (crash_msg.content or "")


async def test_suspend_terminal_unchanged(registry: tuple[ToolRegistry, _OkTool]):
    reg, _ok_b = registry
    sink = EventSink()
    messages, terminal, attempts = await execute_tools(
        [_call("c1", "ask")],
        reg,
        _ctx(),
        sink,
        run_id="r1",
    )

    assert terminal is not None
    assert terminal.effect is ToolEffect.SUSPEND
    assert messages == []
    assert len(attempts) == 1
    assert attempts[0].success is True
    # SUSPEND skips durable tool_use_end (挂起即收口) — live UI has *_required already.
    ends = [e for e in sink._history if e.type == EventType.TOOL_USE_END]  # noqa: SLF001
    assert ends == []
    starts = [e for e in sink._history if e.type == EventType.TOOL_USE_START]  # noqa: SLF001
    assert len(starts) == 1


async def test_multi_terminal_prefers_suspend():
    # Defense (audit F6): when a round somehow yields both HANDOFF and SUSPEND,
    # SUSPEND wins (durable pause must not lose to call-order luck). Normal agent
    # toolsets never hold both; this guards the unreachable race.
    reg = ToolRegistry()
    reg.register(_HandoffTool())
    reg.register(_SuspendTool())
    sink = EventSink()
    # HANDOFF listed first — old "first terminal wins" would pick HANDOFF.
    _messages, terminal, _attempts = await execute_tools(
        [_call("c1", "handoff"), _call("c2", "ask")],
        reg,
        _ctx(),
        sink,
        run_id="r1",
    )
    assert terminal is not None
    assert terminal.effect is ToolEffect.SUSPEND


async def test_captain_role_strips_run_id_from_sse_but_facts_keep_it(
    registry: tuple[ToolRegistry, _OkTool],
):
    """Display/trace split (CEO 自持工具内联): ``role == "captain"`` self-tools omit
    ``run_id`` on the SSE ``tool_use_*`` wire so the UI renders them as turn-level inline
    steps (matching the conformance ``single_agent`` contract — CEO tools have no run_id),
    while the ``tool_call`` fact still keeps the captain ``run_id`` for §8.3 window fold /
    audit. Workers keep ``run_id`` on the wire (their tools scope to a team-graph run
    node). Locks the runtime fix so a later refactor can't silently re-hide CEO retrieval
    behind '正在思考'."""
    from agentcore.runtime.facts import TurnFactLog, current_fact_log

    reg, _ok_b = registry

    cap_log = TurnFactLog()
    token = current_fact_log.set(cap_log)
    try:
        cap_sink = EventSink()
        await execute_tools(
            [_call("c1", "ok_a")], reg, _ctx(), cap_sink, run_id="cap-run", role="captain"
        )
    finally:
        current_fact_log.reset(token)

    cap_events = [
        e
        for e in cap_sink._history  # noqa: SLF001
        if e.type in (EventType.TOOL_USE_START, EventType.TOOL_USE_END)
    ]
    assert cap_events, "captain tool must still emit start/end (only run_id is stripped)"
    assert all("run_id" not in e.payload for e in cap_events)
    tool_facts = [f for f in cap_log.segment_entries() if f["kind"] == "tool_call"]
    assert len(tool_facts) == 1
    assert tool_facts[0]["payload"]["run_id"] == "cap-run"

    wrk_log = TurnFactLog()
    token = current_fact_log.set(wrk_log)
    try:
        wrk_sink = EventSink()
        await execute_tools(
            [_call("w1", "ok_a")], reg, _ctx(), wrk_sink, run_id="w-run", role="worker"
        )
    finally:
        current_fact_log.reset(token)

    wrk_events = [
        e
        for e in wrk_sink._history  # noqa: SLF001
        if e.type in (EventType.TOOL_USE_START, EventType.TOOL_USE_END)
    ]
    assert wrk_events
    assert all(e.payload.get("run_id") == "w-run" for e in wrk_events)


async def test_illegal_json_args_return_explicit_error_not_empty_dict():
    """Illegal tool-call JSON must not silently become ``args={}`` (trace accident chain)."""
    tracked = _OkTool("ok_a", output="alpha")
    reg = ToolRegistry()
    reg.register(tracked)
    # Unescaped quote inside a string — classic model-emitted illegal JSON.
    bad = '{"tasks":[{"role":"研究员","task":"查 "foo" 资料"}]}'
    sink = EventSink()
    with capture_logs() as logs:
        messages, terminal, attempts = await execute_tools(
            [_call("c1", "ok_a", bad)],
            reg,
            _ctx(),
            sink,
            run_id="r1",
        )

    assert terminal is None
    assert tracked.executed is False
    assert len(messages) == 1
    content = messages[0].content or ""
    assert "不是合法 JSON" in content
    assert "失败位置" in content
    assert "原样重发全部参数" in content
    assert "禁止改写" in content
    assert attempts[0].success is False
    assert attempts[0].parse_failure is True
    assert attempts[0].policy_failure is False

    starts = [e for e in sink._history if e.type == EventType.TOOL_USE_START]  # noqa: SLF001
    ends = [e for e in sink._history if e.type == EventType.TOOL_USE_END]  # noqa: SLF001
    assert len(starts) == 1
    assert starts[0].payload.get("arguments") != {}
    assert starts[0].payload.get("arguments", {}).get("__args_parse_failed__") is True
    assert len(ends) == 1
    assert ends[0].payload["status"] == "error"
    assert "不是合法 JSON" in (ends[0].payload.get("result") or "")

    assert any(entry.get("event") == "tool.args_parse_failed" for entry in logs)


async def test_delegate_parse_failure_steers_away_from_nested_arguments():
    """delegate JSON parse fail：明示顶层放 tasks/playbook，禁止再包 arguments。"""
    tracked = _OkTool("delegate", output="ok")
    reg = ToolRegistry()
    reg.register(tracked)
    bad = '{"tasks":[{"role":"A","task":"查 "foo" }]}'
    sink = EventSink()
    messages, terminal, attempts = await execute_tools(
        [_call("c1", "delegate", bad)],
        reg,
        _ctx(),
        sink,
        run_id="r1",
    )
    assert terminal is None
    assert tracked.executed is False
    assert attempts[0].parse_failure is True
    content = messages[0].content or ""
    assert "不是合法 JSON" in content
    assert "禁止再包一层" in content or "禁止再包" in content
    assert "arguments" in content
    assert "tasks" in content
    from agentcore.runtime.runs.playbooks import available_playbooks

    assert available_playbooks() not in content


class _CapturingArgsTool:
    def __init__(self, name: str = "delegate") -> None:
        self._name = name
        self.seen_args: dict[str, Any] | None = None

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.SEARCH,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.seen_args = dict(arguments)
        return ToolResult(tool_call_id="", success=True, output="ok")


def test_unwrap_nested_delegate_arguments_success_and_no_false_positive():
    from agentcore.runtime.engine.tool_protocol_sanitize import (
        unwrap_nested_delegate_arguments,
    )

    inner_tasks = [{"role": "A", "task": "短目标"}]
    nested = {"arguments": json.dumps({"tasks": inner_tasks}, ensure_ascii=False)}
    out = unwrap_nested_delegate_arguments(nested)
    assert out is not None
    assert out["tasks"] == inner_tasks

    as_dict = {"arguments": {"playbook": "build_website", "playbook_args": {"site": "X"}}}
    out2 = unwrap_nested_delegate_arguments(as_dict)
    assert out2 is not None
    assert out2["playbook"] == "build_website"

    # Real top-level tasks + unrelated arguments → do not unwrap.
    mixed = {
        "tasks": inner_tasks,
        "arguments": json.dumps({"tasks": [{"role": "B", "task": "其他"}]}, ensure_ascii=False),
    }
    assert unwrap_nested_delegate_arguments(mixed) is None

    # Empty / garbage inner → no unwrap.
    assert unwrap_nested_delegate_arguments({"arguments": "{not-json"}) is None
    assert unwrap_nested_delegate_arguments({"arguments": {"coordinate": True}}) is None


async def test_execute_tools_unwraps_nested_delegate_arguments():
    """json.loads 成功后窄 unwrap：双包 arguments 到达工具时已是顶层 tasks。"""
    tracked = _CapturingArgsTool("delegate")
    reg = ToolRegistry()
    reg.register(tracked)
    inner = {"tasks": [{"role": "调研", "task": "目标+边界+验收"}], "team_brief": "共享口径"}
    wire = json.dumps({"arguments": json.dumps(inner, ensure_ascii=False)}, ensure_ascii=False)
    sink = EventSink()
    with capture_logs() as logs:
        messages, terminal, attempts = await execute_tools(
            [_call("c1", "delegate", wire)],
            reg,
            _ctx(),
            sink,
            run_id="r1",
        )
    assert terminal is None
    assert attempts[0].success is True
    assert tracked.seen_args is not None
    assert "arguments" not in tracked.seen_args
    assert tracked.seen_args.get("tasks") == inner["tasks"]
    assert tracked.seen_args.get("team_brief") == "共享口径"
    assert any(entry.get("event") == "tool.delegate_arguments_unwrapped" for entry in logs)
    starts = [e for e in sink._history if e.type == EventType.TOOL_USE_START]  # noqa: SLF001
    assert starts and starts[0].payload.get("arguments", {}).get("tasks") == inner["tasks"]


async def test_execute_tools_does_not_unwrap_when_top_level_tasks_present():
    tracked = _CapturingArgsTool("delegate")
    reg = ToolRegistry()
    reg.register(tracked)
    real_tasks = [{"role": "A", "task": "真顶层"}]
    wire = json.dumps(
        {
            "tasks": real_tasks,
            "arguments": json.dumps(
                {"tasks": [{"role": "B", "task": "内层应忽略"}]}, ensure_ascii=False
            ),
        },
        ensure_ascii=False,
    )
    await execute_tools([_call("c1", "delegate", wire)], reg, _ctx(), EventSink(), run_id="r1")
    assert tracked.seen_args is not None
    assert tracked.seen_args["tasks"] == real_tasks
    assert "arguments" in tracked.seen_args


async def test_write_tool_parse_failure_splits_user_and_model_copy():
    """Write-tool JSON parse: UI 人话；模型回执强制分段（勿教用户修转义）。"""
    tracked = _OkTool("file_write", output="written")
    reg = ToolRegistry()
    reg.register(tracked)
    bad = '{"path":"r.md","content":"查 "foo" 资料"}'
    sink = EventSink()
    messages, terminal, attempts = await execute_tools(
        [_call("c1", "file_write", bad)],
        reg,
        _ctx(),
        sink,
        run_id="r1",
    )
    assert terminal is None
    assert tracked.executed is False
    assert attempts[0].parse_failure is True
    model = messages[0].content or ""
    assert "不是合法 JSON" in model
    assert "分段" in model or "短骨架" in model
    assert "原样重发全部参数" not in model
    ends = [e for e in sink._history if e.type == EventType.TOOL_USE_END]  # noqa: SLF001
    assert len(ends) == 1
    ui = ends[0].payload.get("result") or ""
    assert "长文保存失败" in ui
    assert "分段" in ui
    assert "原样重发" not in ui
    assert "失败位置" not in ui


async def test_code_execute_maps_sandbox_error_to_failed_result():
    backend = _FakeBackend(raise_sandbox=True)
    result = await CodeExecuteTool().execute(
        {"code": "print(1)", "language": "python"},
        _ctx(backend),  # type: ignore[arg-type]
    )

    assert result.success is False
    assert "代码执行环境启动失败" in (result.error or "")


async def test_execute_tools_denies_tool_outside_allowlist():
    """Least-privilege: registry may hold file_write, but allow-list must block execute."""
    fw = _OkTool("file_write", output="written")
    read = _OkTool("file_read", output="ok")
    reg = ToolRegistry()
    reg.register(fw)
    reg.register(read)
    sink = EventSink()
    messages, terminal, attempts = await execute_tools(
        [_call("c1", "file_write", '{"path":"AgentCore/文档/research/x.md","content":"n"}')],
        reg,
        _ctx(),
        sink,
        run_id="debate_r1_plaintiff",
        allowed_tool_names=["file_read", "web_search"],
    )
    assert fw.executed is False
    assert terminal is None
    assert len(messages) == 1
    assert attempts[0].success is False
    assert attempts[0].policy_failure is True
    assert "允许列表" in (messages[0].content or "")
    assert "handoff" in (messages[0].content or "") or "escalate" in (messages[0].content or "")
    assert "勿用正文冒充落盘" in (messages[0].content or "")
    assert "产物请改经 handoff 正文回报" not in (messages[0].content or "")
    from agentcore.runtime.engine.tool_exec import TOOL_FAILED_MARKER

    assert TOOL_FAILED_MARKER in (messages[0].content or "")
    ends = [e for e in sink._history if e.type == EventType.TOOL_USE_END]  # noqa: SLF001
    assert len(ends) == 1
    assert ends[0].payload.get("status") == "error"


async def test_execute_tools_allowlist_none_permits_registry_tool():
    fw = _OkTool("file_write", output="written")
    reg = ToolRegistry()
    reg.register(fw)
    messages, _terminal, attempts = await execute_tools(
        [_call("c1", "file_write")],
        reg,
        _ctx(),
        EventSink(),
        allowed_tool_names=None,
    )
    assert fw.executed is True
    assert attempts[0].success is True
    assert messages[0].content == "written"


async def test_files_touched_uses_execution_success_not_intent():
    """DRIFT fix: denied / failed file_write must not enter files_touched; success must."""
    from agentcore.llm.provider.protocol import LLMMessage
    from agentcore.runtime.engine.tool_exec import TOOL_FAILED_MARKER
    from agentcore.runtime.runs.serialize import files_touched_from_transcript

    class _FailWrite(_OkTool):
        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            self.executed = True
            return ToolResult(tool_call_id="", success=False, error="disk full")

    # 1) allowlist deny → marker + no harvest
    fw = _OkTool("file_write", output="written")
    reg = ToolRegistry()
    reg.register(fw)
    denied, _, _ = await execute_tools(
        [_call("c1", "file_write", '{"path":"ghost.md","content":"n"}')],
        reg,
        _ctx(),
        EventSink(),
        allowed_tool_names=["file_read"],
    )
    assistant_deny = LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[_call("c1", "file_write", '{"path":"ghost.md","content":"n"}')],
    )
    assert TOOL_FAILED_MARKER in (denied[0].content or "")
    assert "handoff" in (denied[0].content or "")
    assert files_touched_from_transcript([assistant_deny, denied[0]]) == []

    # 2) successful write → harvested
    ok_reg = ToolRegistry()
    ok_reg.register(_OkTool("file_write", output="written"))
    ok_msgs, _, _ = await execute_tools(
        [_call("c2", "file_write", '{"path":"ok.md","content":"y"}')],
        ok_reg,
        _ctx(),
        EventSink(),
        allowed_tool_names=None,
    )
    assistant_ok = LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[_call("c2", "file_write", '{"path":"ok.md","content":"y"}')],
    )
    assert TOOL_FAILED_MARKER not in (ok_msgs[0].content or "")
    assert files_touched_from_transcript([assistant_ok, ok_msgs[0]]) == ["ok.md"]

    # 3) tool returned success=False → marker + no harvest
    fail_reg = ToolRegistry()
    fail_reg.register(_FailWrite("file_write"))
    fail_msgs, _, _ = await execute_tools(
        [_call("c3", "file_write", '{"path":"io_err.md","content":"z"}')],
        fail_reg,
        _ctx(),
        EventSink(),
        allowed_tool_names=None,
    )
    assistant_fail = LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[_call("c3", "file_write", '{"path":"io_err.md","content":"z"}')],
    )
    assert TOOL_FAILED_MARKER in (fail_msgs[0].content or "")
    assert files_touched_from_transcript([assistant_fail, fail_msgs[0]]) == []


async def test_execute_tools_forwards_contract_failure_to_attempt():
    """ToolResult.contract_failure 沿 attempt 构造链路传到 ToolAttempt（断路器据此跳过）。"""
    reg = ToolRegistry()
    reg.register(_ContractRejectTool("web_search"))
    messages, terminal, attempts = await execute_tools(
        [_call("c1", "web_search", '{"query":"a b c d e f g h"}')],
        reg,
        _ctx(),
        EventSink(),
        run_id="r1",
    )
    assert terminal is None
    assert attempts[0].success is False
    assert attempts[0].contract_failure is True
    assert attempts[0].policy_failure is False
    assert "查询词过多" in (messages[0].content or "")


async def test_execute_end_error_carries_aggregable_reason():
    """status=error 的 tool.execute_end 必须带简短可聚合 reason（排查勿靠相邻事件）。"""
    reg = ToolRegistry()
    reg.register(_ContractRejectTool("web_search"))
    with capture_logs() as logs:
        await execute_tools(
            [_call("c1", "web_search", '{"query":"a b c d e f g h"}')],
            reg,
            _ctx(),
            EventSink(),
            run_id="r1",
        )
    ends = [e for e in logs if e.get("event") == "tool.execute_end"]
    assert len(ends) == 1
    assert ends[0]["status"] == "error"
    assert ends[0]["tool"] == "web_search"
    reason = ends[0].get("reason") or ""
    assert "查询词过多" in reason
    assert "\n" not in reason


async def test_execute_end_ok_omits_reason():
    reg = ToolRegistry()
    reg.register(_OkTool())
    with capture_logs() as logs:
        await execute_tools(
            [_call("c1", "ok")],
            reg,
            _ctx(),
            EventSink(),
            run_id="r1",
        )
    ends = [e for e in logs if e.get("event") == "tool.execute_end"]
    assert len(ends) == 1
    assert ends[0]["status"] == "ok"
    assert "reason" not in ends[0]


@pytest.mark.asyncio
async def test_same_batch_handoff_waits_for_sibling_write(tmp_path: Path):
    """同批 file_write+handoff：handoff 须在 write 之后执行，才能看到 prose stamp。"""
    import asyncio
    import json

    from agentcore.tools.builtin.file_ops import FileWriteTool
    from agentcore.tools.builtin.handoff import HandoffTool

    order: list[str] = []
    prose = "# 报告\n\n" + ("这是实质正文段落。" * 50)
    assert len(prose) >= 400

    class _SlowWrite(FileWriteTool):
        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            order.append("write_start")
            await asyncio.sleep(0.05)
            result = await super().execute(arguments, context)
            order.append("write_end")
            return result

    class _OrderHandoff(HandoffTool):
        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            order.append("handoff")
            return await super().execute(arguments, context)

    reg = ToolRegistry()
    reg.register(_SlowWrite())
    reg.register(_OrderHandoff())
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox()),
        user_id="u",
        handoff_requires_body=True,
        round_content_chars=0,
    )
    write_args = json.dumps({"path": "notes.md", "content": prose}, ensure_ascii=False)
    handoff_args = json.dumps({"summary": "调研已落盘"}, ensure_ascii=False)
    # handoff listed first — without phasing it would race ahead of slow write.
    messages, terminal, attempts = await execute_tools(
        [
            _call("c_h", "handoff", handoff_args),
            _call("c_w", "file_write", write_args),
        ],
        reg,
        ctx,
        EventSink(),
        run_id="r1",
    )
    assert order[:2] == ["write_start", "write_end"]
    assert order[-1] == "handoff"
    assert attempts[0].success is True  # handoff (call order)
    assert attempts[1].success is True  # write
    assert terminal is not None
    assert terminal.success is True
    assert ctx.landed_artifact_kinds.get("notes.md") == "prose"
    assert len(messages) == 2


async def test_test_run_maps_sandbox_error_to_failed_result(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeBackend(raise_sandbox=True)

    async def _profile(_backend):
        from agentcore.runtime.context.workspace_profile import WorkspaceProfile

        return WorkspaceProfile(
            languages=["python"],
            frameworks=[],
            package_managers=[],
            test_commands=["pytest"],
        )

    async def _framework(_backend, _profile, _arg):
        return "pytest"

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run._detect_framework",
        _framework,
    )

    result = await TestRunTool().execute({"scope": "all"}, _ctx(backend))  # type: ignore[arg-type]

    assert result.success is False
    assert "代码执行环境启动失败" in (result.error or "")


async def test_parallel_same_path_file_read_coalesces_once(tmp_path: Path):
    """Same-round parallel file_read on one path → one underlying read, fan-out results."""
    from agentcore.tools.builtin.file_ops import FileReadTool

    (tmp_path / "doc.md").write_text("# Hello\nshared body\n", encoding="utf-8")
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    reads = {"n": 0}
    orig_read = backend.read

    async def _counting_read(path: str, *args: Any, **kwargs: Any) -> str:
        reads["n"] += 1
        return await orig_read(path, *args, **kwargs)

    backend.read = _counting_read  # type: ignore[method-assign]

    reg = ToolRegistry()
    reg.register(FileReadTool())
    ctx = _ctx(backend)
    sink = EventSink()
    args = '{"path": "doc.md"}'
    messages, terminal, attempts = await execute_tools(
        [
            _call("r1", "file_read", args),
            _call("r2", "file_read", args),
            _call("r3", "file_read", args),
        ],
        reg,
        ctx,
        sink,
        run_id="r1",
    )

    assert terminal is None
    assert len(messages) == 3
    assert all(a.success for a in attempts)
    assert reads["n"] == 1
    assert ctx.file_read_counts.get("doc.md") == 1
    bodies = [m.content or "" for m in messages]
    assert all("shared body" in b for b in bodies)
    # Each call still gets its own tool_use_start/end on the wire.
    starts = [e for e in sink._history if e.type == EventType.TOOL_USE_START]  # noqa: SLF001
    ends = [e for e in sink._history if e.type == EventType.TOOL_USE_END]  # noqa: SLF001
    assert {e.payload["tool_call_id"] for e in starts} == {"r1", "r2", "r3"}
    assert {e.payload["tool_call_id"] for e in ends} == {"r1", "r2", "r3"}


async def test_parallel_distinct_path_file_reads_not_coalesced(tmp_path: Path):
    """Different paths in one round still each execute (no cross-path fan-out)."""
    from agentcore.tools.builtin.file_ops import FileReadTool

    (tmp_path / "a.md").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.md").write_text("BBB", encoding="utf-8")
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    reads = {"n": 0}
    orig_read = backend.read

    async def _counting_read(path: str, *args: Any, **kwargs: Any) -> str:
        reads["n"] += 1
        return await orig_read(path, *args, **kwargs)

    backend.read = _counting_read  # type: ignore[method-assign]

    reg = ToolRegistry()
    reg.register(FileReadTool())
    ctx = _ctx(backend)
    messages, _terminal, attempts = await execute_tools(
        [
            _call("r1", "file_read", '{"path": "a.md"}'),
            _call("r2", "file_read", '{"path": "b.md"}'),
        ],
        reg,
        ctx,
        EventSink(),
        run_id="r1",
    )
    assert all(a.success for a in attempts)
    assert reads["n"] == 2
    assert ctx.file_read_counts.get("a.md") == 1
    assert ctx.file_read_counts.get("b.md") == 1
    by_id = {m.tool_call_id: m.content or "" for m in messages}
    assert "AAA" in by_id["r1"]
    assert "BBB" in by_id["r2"]

async def test_prose_withheld_str_replace_miss_not_audience_deny():
    """D2: form=prose miss must not say「请用 delegate」."""
    from dataclasses import replace

    reg = ToolRegistry()
    # Write tools absent from registry (simulates prose withhold strip).
    reg.register(_OkTool("file_read"))
    ctx = replace(_ctx(), withheld_write_tools="prose")
    messages, _terminal, attempts = await execute_tools(
        [_call("c1", "str_replace", '{"path": "a.py", "old_string": "x", "new_string": "y"}')],
        reg,
        ctx,
        EventSink(),
        run_id="r1",
    )
    assert attempts[0].success is False
    assert attempts[0].policy_failure is True
    content = messages[0].content or ""
    assert "仅文字" in content or "form=prose" in content
    assert "escalate" in content
    assert "请用 delegate" not in content
    assert "delegate 派工" not in content


async def test_ceo_str_replace_miss_still_audience_deny():
    """D2 regression: CEO face without withhold stamp keeps delegate tip."""
    reg = ToolRegistry()
    reg.register(_OkTool("delegate"))
    ctx = _ctx()  # withheld_write_tools=None
    messages, _terminal, attempts = await execute_tools(
        [_call("c1", "str_replace", "{}")],
        reg,
        ctx,
        EventSink(),
        run_id="",
        role="captain",
    )
    content = messages[0].content or ""
    assert "delegate" in content.lower() or "派工" in content
    assert "form=prose" not in content


async def test_prose_allowlist_deny_no_handoff_as_write():
    """D2: allowlist deny on write tools under prose withhold uses escalate copy."""
    from dataclasses import replace

    reg = ToolRegistry()
    reg.register(_OkTool("str_replace"))
    ctx = replace(_ctx(), withheld_write_tools="prose")
    messages, _terminal, attempts = await execute_tools(
        [_call("c1", "str_replace", "{}")],
        reg,
        ctx,
        EventSink(),
        run_id="r1",
        allowed_tool_names=["file_read", "handoff"],  # write tool not allowed
    )
    content = messages[0].content or ""
    assert "form=prose" in content or "仅文字" in content
    assert "产物请改经 handoff 正文回报" not in content
    assert "请用 delegate" not in content


async def test_captain_browser_navigate_skips_approval_gate():
    """CEO 窄例外：captain 直调 browser_navigate 不弹审批。"""
    from agentcore.core.types import ToolApproval

    class _GrantableNavigate:
        executed = False

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="browser_navigate",
                description="stub",
                parameters={"type": "object", "properties": {}},
                category=ToolCategory.EXECUTION,
                approval=ToolApproval.GRANTABLE,
            )

        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            self.executed = True
            return ToolResult(tool_call_id="", success=True, output="opened")

    class _GateThatMustNotPrompt:
        permission_axes = None

        def will_prompt(self, *args, **kwargs) -> bool:
            raise AssertionError("captain browser_navigate must not prompt")

        async def authorize(self, *args, **kwargs):
            raise AssertionError("captain browser_navigate must not authorize")

    tool = _GrantableNavigate()
    reg = ToolRegistry()
    reg.register(tool)
    await execute_tools(
        [_call("c1", "browser_navigate", '{"url":"https://example.com"}')],
        reg,
        _ctx(),
        EventSink(),
        run_id="cap-run",
        role="captain",
        approval_gate=_GateThatMustNotPrompt(),  # type: ignore[arg-type]
    )
    assert tool.executed is True
