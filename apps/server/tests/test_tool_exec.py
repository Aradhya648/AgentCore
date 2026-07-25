"""Tests for parallel tool execution and per-tool exception firewall (audit/05 P2-1)."""

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
    assert "handoff" in (messages[0].content or "")
    assert "勿再尝试写盘" in (messages[0].content or "")
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
