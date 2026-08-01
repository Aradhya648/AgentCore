"""同人续派（delegate.continue_from_run_id）— 成功路径、校验失败分支、唤回闸、同批组合。"""

from pathlib import Path

from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, TokenUsage
from agentcore.runtime.delegate.continuation import (
    ContinuationRejectedError,
    merge_continuation_tools,
    register_completed_session,
    resolve_session,
    run_continuation,
)
from agentcore.runtime.delegate.drive import drive
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs import (
    RunSession,
    WaveScheduler,
    build_agent_executor,
    build_run_plan,
)
from agentcore.runtime.runs.constants import DEFAULT_RECALL_LIMIT
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from agentcore.runtime.sessions import SessionStore
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.protocol import ToolCategory, ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.delegate.conftest import _upstream_body


class _NamedStub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.schema = ToolSchema(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.SEARCH,
        )

    async def execute(self, arguments, context):  # noqa: ARG002
        return ToolResult(tool_call_id="", success=True, output="ok")


def _register_names(reg: ToolRegistry, *names: str) -> None:
    for n in names:
        reg.register(_NamedStub(n))


class _Provider:
    def __init__(self, contents: list[str], usage: TokenUsage | None = None) -> None:
        self._contents = [_upstream_body(c) for c in contents]
        self._usage = usage
        self.calls = 0

    async def stream(self, request):
        text = self._contents[self.calls] if self.calls < len(self._contents) else "done"
        self.calls += 1
        yield LLMChunk(delta_content=text)
        if self._usage is not None:
            yield LLMChunk(usage=self._usage)


def _ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="CEO",
        agent_id="CEO",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


def _tool(store: SessionStore, provider: _Provider, sink: EventSink | None = None) -> DelegateTool:
    return DelegateTool(
        llm=provider,
        sink=sink or EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=_ctx(),
        captain_run_id="CEO",
        session_store=store,
    )


async def _seed(store: SessionStore, provider: _Provider, *, run_id: str = "t_1") -> RunSession:
    plan, _ = build_run_plan(
        [{"role": "研究员", "task": "做A"}], id_prefix="t", parent_run_id="CEO"
    )
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=ToolRegistry(),
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="原始请求",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    state = res[run_id]
    session = RunSession(
        run_id=run_id,
        spec=plan.by_id(run_id),
        transcript=state.transcript,
        content=state.content,
    )
    store.put(session)
    return session


async def test_continue_from_hit_returns_product_and_bumps_recall():
    store = SessionStore()
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    provider = _Provider(["第一版", "续写版"], usage=usage)
    await _seed(store, provider)
    sink = EventSink()
    tool = _tool(store, provider, sink)

    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "把语气改正式并补风险",
                    "continue_from_run_id": "t_1",
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )

    assert result.success is True
    assert "续写版" in result.output
    assert store.get("t_1").recall_count == 1
    assert store.get("t_1").content == _upstream_body("续写版")
    assert tool.continuation_count == 1
    sink.close()
    events = [e async for e in sink]
    started = [
        e
        for e in events
        if e.type is EventType.RUN_STARTED and e.payload.get("continues_run_id")
    ]
    assert started
    assert started[0].payload["continues_run_id"] == "t_1"
    assert started[0].payload["parent_run_id"] == "CEO"
    assert "revision" not in started[0].payload


async def test_continue_from_miss_rejects_with_cold_hint():
    store = SessionStore()
    provider = _Provider(["x"])
    tool = _tool(store, provider)
    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "接着干",
                    "continue_from_run_id": "ghost",
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result.success is True
    assert "冷委派" in result.output or "找不到" in result.output
    assert tool.continuation_count == 0


async def test_continue_from_self_ref_rejected():
    store = SessionStore()
    provider = _Provider(["第一版"])
    await _seed(store, provider)
    tool = _tool(store, provider)
    try:
        await resolve_session(tool, "t_1", own_run_id="t_1")
        raise AssertionError("expected ContinuationRejectedError")
    except ContinuationRejectedError as exc:
        assert "自指" in exc.message


async def test_continue_from_capped_rejects():
    store = SessionStore()
    provider = _Provider(["第一版", "续"])
    session = await _seed(store, provider)
    session.recall_count = DEFAULT_RECALL_LIMIT
    store.put(session)
    tool = _tool(store, provider)
    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "再改",
                    "continue_from_run_id": "t_1",
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert "上限" in result.output
    assert tool.continuation_count == 0


async def test_same_batch_depends_on_plus_continue_from():
    """单个 run 完成即登记 → 同批 depends_on X + continue_from X 成立。"""
    store = SessionStore()
    provider = _Provider(["调研稿", "续写实现"])
    tool = _tool(store, provider, EventSink())
    plan, errs = build_run_plan(
        [
            {"id": "a", "role": "研究员", "task": "先调研"},
            {
                "id": "b",
                "role": "研究员",
                "task": "据调研接着写",
                "depends_on": ["a"],
                "continue_from_run_id": "p_a",
            },
        ],
        id_prefix="p",
        parent_run_id="CEO",
    )
    assert not errs
    assert plan.by_id("p_b").continue_from_run_id == "p_a"

    out = await drive(
        tool,
        plan,
        execution_id="e",
        finalize=False,
        call_idx=1,
        seed_notes=None,
        complexity_hint="standard",
        completion_criteria=None,
        session=None,
        seed_completed=None,
        coordinate=False,
    )
    assert out.success is True
    assert "续写实现" in out.output
    assert store.get("p_a") is not None
    assert store.get("p_a").recall_count == 1
    assert tool.continuation_count == 1


# --- 验收失败的 run 保留现场：终局 FAILED 可续派 --------------------------------------


def _failed_state(*, content: str = "失败草稿", transcript: bool = True) -> RunState:
    return RunState(
        phase=RunPhase.FAILED,
        content=content,
        error="缺少必备章节：结论",
        transcript=(
            [LLMMessage(role="assistant", content=content)] if transcript else []
        ),
    )


def test_register_completed_session_registers_failed_with_transcript():
    """终局 FAILED + transcript 非空 → 登记现场（否则 continue_from 找不到现场）。"""
    store = SessionStore()
    tool = _tool(store, _Provider(["x"]))
    plan = RunPlan(nodes=[RunSpec(run_id="t_1", task="写论文", role="研究员")])
    sess = register_completed_session(tool, plan, "t_1", _failed_state())
    assert sess is not None
    assert store.get("t_1") is not None
    assert store.get("t_1").content == "失败草稿"


def test_register_skips_failed_without_transcript():
    """异常崩溃在任何产出前就 FAILED（无 transcript）→ 无现场可续，不登记。"""
    store = SessionStore()
    tool = _tool(store, _Provider(["x"]))
    plan = RunPlan(nodes=[RunSpec(run_id="t_1", task="t")])
    assert (
        register_completed_session(tool, plan, "t_1", _failed_state(transcript=False))
        is None
    )
    assert store.get("t_1") is None


async def test_resolve_session_allows_terminal_failed():
    store = SessionStore()
    tool = _tool(store, _Provider(["x"]))
    spec = RunSpec(run_id="t_1", task="写论文", role="研究员")
    store.put(
        RunSession(
            run_id="t_1",
            spec=spec,
            transcript=[LLMMessage(role="assistant", content="失败草稿")],
            content="失败草稿",
        )
    )
    completed = {"t_1": RunState(phase=RunPhase.FAILED, error="x")}
    session = await resolve_session(tool, "t_1", own_run_id="t_2", completed=completed)
    assert session.run_id == "t_1"


async def test_resolve_session_rejects_in_progress():
    """真正进行中（未终局）的目标仍拒 — 避免竞态读半成品。"""
    store = SessionStore()
    tool = _tool(store, _Provider(["x"]))
    completed = {"t_1": RunState(phase=RunPhase.RUNNING)}
    try:
        await resolve_session(tool, "t_1", own_run_id="t_2", completed=completed)
        raise AssertionError("expected ContinuationRejectedError")
    except ContinuationRejectedError as exc:
        assert "进行中" in exc.message


async def test_continuation_rejected_is_non_retryable():
    """续派拒绝折成 FAILED 时标记不可重试，避免调度层同错重放两次。"""
    store = SessionStore()
    tool = _tool(store, _Provider(["x"]))
    spec = RunSpec(run_id="t_2", task="接着写", continue_from_run_id="ghost")
    state = await run_continuation(tool, spec, {}, execution_id="e")
    assert state.phase is RunPhase.FAILED
    assert state.error_retryable is False


async def test_continuation_rejected_emits_run_failed():
    """拒续派须发 run_failed，否则协作图节点卡在「排队中」。"""
    store = SessionStore()
    sink = EventSink()
    tool = _tool(store, _Provider(["x"]), sink)
    spec = RunSpec(
        run_id="t_tip",
        agent_id="t_tip",
        task="接着写",
        continue_from_run_id="ghost",
    )
    state = await run_continuation(tool, spec, {}, execution_id="e")
    assert state.phase is RunPhase.FAILED
    sink.close()
    events = [e async for e in sink]
    failed = [e for e in events if e.type is EventType.RUN_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["run_id"] == "t_tip"
    assert "找不到" in failed[0].payload["error"]


async def test_continue_from_chain_tip_alias_resolves_to_root():
    """续派成功后登记链末端→根别名；下一跳填图上末端仍可溯根。"""
    store = SessionStore()
    provider = _Provider(["第一版", "续写版", "再续一版"])
    await _seed(store, provider)
    sink = EventSink()
    tool = _tool(store, provider, sink)

    result = await tool.execute(
        {
            "tasks": [
                {
                    "id": "rev1",
                    "role": "研究员",
                    "task": "改一版",
                    "continue_from_run_id": "t_1",
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result.success is True
    # 续派节点 id 形如 del_*_rev1 或带 prefix；从 sink 取 continues 链末端
    sink.close()
    events = [e async for e in sink]
    started = [
        e
        for e in events
        if e.type is EventType.RUN_STARTED and e.payload.get("continues_run_id") == "t_1"
    ]
    assert started
    tip_id = started[0].payload["run_id"]
    assert tip_id != "t_1"
    assert store.get(tip_id) is not None
    assert store.get(tip_id).run_id == "t_1"
    assert store.root_for_alias(tip_id) == "t_1"

    # 第二跳：continue_from 填链末端
    sink2 = EventSink()
    tool2 = _tool(store, provider, sink2)
    result2 = await tool2.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "再改一版",
                    "continue_from_run_id": tip_id,
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result2.success is True
    assert "再续一版" in result2.output or tool2.continuation_count >= 1
    assert store.get("t_1").recall_count >= 2


async def test_continue_from_failed_run_is_allowed():
    """端到端：CEO 用 continue_from 让原作者在失败草稿上改写。"""
    store = SessionStore()
    provider = _Provider(["续写修正版：已补齐结论章节"])
    spec = RunSpec(run_id="t_1", task="写论文", role="研究员")
    store.put(
        RunSession(
            run_id="t_1",
            spec=spec,
            transcript=[
                LLMMessage(role="system", content="SYS"),
                LLMMessage(role="user", content="写论文"),
                LLMMessage(role="assistant", content="失败草稿，缺结论"),
            ],
            content="失败草稿，缺结论",
        )
    )
    tool = _tool(store, provider, EventSink())
    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "补齐结论章节",
                    "continue_from_run_id": "t_1",
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result.success is True
    assert "续写修正版" in result.output
    assert store.get("t_1").recall_count == 1


# ── D1：tools 只增不减 ───────────────────────────────────────────────────────


def test_merge_continuation_tools_undeclared_keeps_prior():
    assert merge_continuation_tools(["file_read", "grep"], None) == [
        "file_read",
        "grep",
    ]
    assert merge_continuation_tools(None, None) is None


def test_merge_continuation_tools_superset_adds():
    assert merge_continuation_tools(
        ["file_read", "grep"],
        ["file_read", "grep", "test_run"],
    ) == ["file_read", "grep", "test_run"]
    assert merge_continuation_tools(["file_read"], ["test_run"]) == [
        "file_read",
        "test_run",
    ]


def test_merge_continuation_tools_subset_does_not_shrink():
    assert merge_continuation_tools(
        ["file_read", "grep", "test_run"],
        ["file_read"],
    ) == ["file_read", "grep", "test_run"]


def test_merge_continuation_tools_unrestricted_prior_stays_open():
    """原现场 tools=None（无限制）不得被白名单声明减面。"""
    assert merge_continuation_tools(None, ["file_read"]) is None


async def test_continue_from_tools_superset_is_effective_on_session():
    """乙续派声明更大 tools → session / 续写有效面为超集。"""
    store = SessionStore()
    provider = _Provider(["第一版", "续写版"])
    await _seed(store, provider)
    session = store.get("t_1")
    assert session is not None
    # 模拟调查批只读面
    from dataclasses import replace

    session.spec = replace(
        session.spec,
        tools=["file_read", "grep", "web_search"],
    )
    store.put(session)

    sink = EventSink()
    tool = _tool(store, provider, sink)
    _register_names(
        tool._tools, "file_read", "grep", "web_search", "test_run", "str_replace"
    )

    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "按结论改码并验",
                    "continue_from_run_id": "t_1",
                    "tools": ["file_read", "grep", "web_search", "test_run", "str_replace"],
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result.success is True
    effective = store.get("t_1").spec.tools
    assert effective is not None
    assert "test_run" in effective
    assert "str_replace" in effective
    assert "file_read" in effective


async def test_continue_from_tools_subset_does_not_shrink_session():
    """试图减面 → 保持原超集。"""
    store = SessionStore()
    provider = _Provider(["第一版", "续写版"])
    await _seed(store, provider)
    session = store.get("t_1")
    from dataclasses import replace

    session.spec = replace(
        session.spec,
        tools=["file_read", "grep", "test_run"],
    )
    store.put(session)

    tool = _tool(store, provider)
    _register_names(tool._tools, "file_read", "grep", "test_run")

    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "只读复核",
                    "continue_from_run_id": "t_1",
                    "tools": ["file_read"],
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result.success is True
    effective = store.get("t_1").spec.tools
    assert effective == ["file_read", "grep", "test_run"]


async def test_continue_from_undeclared_tools_keeps_session_tools():
    store = SessionStore()
    provider = _Provider(["第一版", "续写版"])
    await _seed(store, provider)
    session = store.get("t_1")
    from dataclasses import replace

    session.spec = replace(session.spec, tools=["file_read", "grep"])
    store.put(session)

    tool = _tool(store, provider)
    _register_names(tool._tools, "file_read", "grep")

    result = await tool.execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "task": "接着写",
                    "continue_from_run_id": "t_1",
                }
            ],
            "coordinate": False,
            "complexity_hint": "light",
        },
        _ctx(),
    )
    assert result.success is True
    assert store.get("t_1").spec.tools == ["file_read", "grep"]
