from dataclasses import replace

from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.llm.provider.protocol import LLMChunk, ToolCallDelta
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.executor import build_agent_executor
from agentcore.runtime.runs.executor_identities import LeadSubteam
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec
from agentcore.runtime.runs.wave import WaveScheduler
from agentcore.tools.builtin.escalate import EscalateTool
from agentcore.tools.protocol import ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from tests.runs_executor.conftest import (
    _ContentProvider,
    _ctx,
    _executor,
    _ScriptedRounds,
)


class _StubDelegate:
    """A minimal ORCHESTRATION tool named 'delegate' — never executed here; the
    fake LLM emits no tool call, so we only assert it was (or wasn't) minted."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="delegate",
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments, context) -> ToolResult:  # noqa: ANN001
        return ToolResult(tool_call_id="", success=True, output="")


async def _noop_dispose() -> None:
    return None


def _stub_subteam() -> LeadSubteam:
    """The factory's return shape (受监督子计划 B): a lead's delegate + replan bundle. These
    identity / depth-cap tests only care that a bundle is minted (not its contents), so one
    stub delegate with a no-op dispose stands in for the real make_lead_subteam output."""
    stub = _StubDelegate()
    return LeadSubteam(tools=(stub,), tool_names=(stub.schema.name,), dispose=_noop_dispose)


def _spec(run_id: str, *, depth: int):
    return RunSpec(
        run_id=run_id,
        agent_id=run_id,
        role="W",
        task="t",
        depth=depth,
    )


def _nesting_executor(plan: RunPlan, provider, factory):
    return build_agent_executor(
        plan=plan,
        llm=provider,
        tools=ToolRegistry(),
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="原始请求",
        execution_id="e",
        delegate_factory=factory,
    )


async def test_nested_delegate_offered_only_within_depth_cap():
    calls: list[tuple[str, int]] = []

    def factory(captain_run_id: str, captain_depth: int):
        calls.append((captain_run_id, captain_depth))
        return _stub_subteam()

    plan = RunPlan()
    plan.add(_spec("d1", depth=1))
    plan.add(_spec("d2", depth=2))  # at the cap
    executor = _nesting_executor(plan, _ContentProvider(["X", "Y"]), factory)
    await executor(plan.by_id("d1"), {})
    await executor(plan.by_id("d2"), {})
    # The depth-1 worker (within the cap) is handed a delegate tool bound to itself;
    # the depth-2 worker (at the cap) never is — delegation is on by default, the
    # depth cap is the hard stop.
    assert calls == [("d1", 1)]


async def test_nested_delegate_withheld_at_depth_cap():
    calls: list[str] = []

    def factory(captain_run_id: str, captain_depth: int):
        calls.append(captain_run_id)
        return _stub_subteam()

    plan = RunPlan()
    plan.add(_spec("d2", depth=2))  # at the cap
    executor = _nesting_executor(plan, _ContentProvider(["X"]), factory)
    await executor(plan.by_id("d2"), {})
    assert calls == []  # depth-2 sub-worker → leaf, no delegate tool


async def test_captain_worker_gets_captain_identity_and_delegate_tool():
    provider = _ContentProvider(["X"])
    plan = RunPlan()
    plan.add(_spec("d1", depth=1))
    executor = _nesting_executor(plan, provider, lambda rid, d: _stub_subteam())
    await executor(plan.by_id("d1"), {})
    # A within-cap worker is told it may lead one nested sub-team (on by default).
    assert "再向下委派一层子团队" in provider.system_messages[0]


async def test_default_worker_is_captain_within_depth_cap():
    provider = _ContentProvider(["X"])
    plan, _ = build_run_plan([{"role": "A", "task": "做A"}], id_prefix="t")
    # Delegation is on by default — a depth-1 worker within the cap is a captain.
    executor = _nesting_executor(plan, provider, lambda rid, d: _stub_subteam())
    await executor(plan.by_id("t_1"), {})
    sys = provider.system_messages[0]
    # Captain-only markers — the leaf intro carries neither.
    assert "再向下委派一层子团队" in sys
    assert "不要为委派而委派" in sys


async def test_captain_identity_carries_when_to_split_guidance():
    provider = _ContentProvider(["X"])
    plan, _ = build_run_plan([{"role": "A", "task": "做A"}], id_prefix="t")
    executor = _nesting_executor(plan, provider, lambda rid, d: _stub_subteam())
    await executor(plan.by_id("t_1"), {})
    sys = provider.system_messages[0]
    assert "再向下委派一层子团队" in sys
    assert "不要为委派而委派" in sys
    assert "3+" in sys and "独立子系统" in sys
    assert "深入实现" in sys
    assert "4 个 sub-worker" in sys


async def test_depth_two_subworker_keeps_leaf_identity():
    provider = _ContentProvider(["X"])
    plan, _ = build_run_plan(
        [{"role": "A", "task": "做A"}],
        id_prefix="t",
        parent_run_id="cap",
        depth=2,
    )
    # At the depth cap: delegate tools withheld — depth-2 sub-workers are always leaves.
    executor = _nesting_executor(plan, provider, lambda rid, d: _stub_subteam())
    await executor(plan.by_id("t_1"), {})
    assert "不能再向下委派" in provider.system_messages[0]
    assert "再向下委派一层子团队" not in provider.system_messages[0]


async def test_worker_identities_carry_tool_safety_caution():
    # 按角色 right-size (反向): the environment-mutation caution (<tool_safety>) moved OUT of
    # the shared base (where the read-only coordinator CEO carried it inertly) INTO the worker
    # identities — workers hold the mutating tools (file_write / code_execute / file_delete…),
    # so the caution rides them now. Pin it on BOTH the leaf and the captain identity so a
    # refactor can't drop the mutation caution from the agents that can actually act
    # (the absence-from-base/CEO side is pinned in tests/test_prompt.py).
    leaf_provider = _ContentProvider(["X"])
    leaf_plan, _ = build_run_plan(
        [{"role": "A", "task": "做A"}],
        id_prefix="t",
        parent_run_id="cap",
        depth=2,  # depth cap → leaf identity
    )
    leaf_exec = _nesting_executor(leaf_plan, leaf_provider, lambda rid, d: _stub_subteam())
    await leaf_exec(leaf_plan.by_id("t_1"), {})
    leaf_sys = leaf_provider.system_messages[0]
    assert "<tool_safety>" in leaf_sys
    assert "本地模式" in leaf_sys

    captain_provider = _ContentProvider(["Y"])
    captain_plan = RunPlan()
    captain_plan.add(_spec("d1", depth=1))
    captain_exec = _nesting_executor(captain_plan, captain_provider, lambda rid, d: _stub_subteam())
    await captain_exec(captain_plan.by_id("d1"), {})
    captain_sys = captain_provider.system_messages[0]
    assert "再向下委派一层子团队" in captain_sys  # captain identity in play
    assert "<tool_safety>" in captain_sys


async def test_handoff_prompt_splits_by_topology():
    """Identity handoff wording tracks DAG dependents (接力契约 + 增量交代).

    Upstream (has_dependents) gets the imperative「必须调用」; a leaf gets the
    conditional「有增量才写 / 不必为交而交」— same semantics as the engine gate
    and the handoff tool description, without fighting either.
    """
    from agentcore.runtime.runs.executor_identities import build_worker_identity
    from agentcore.tools.builtin.handoff import HandoffTool

    upstream = build_worker_identity(has_dependents=True, captain=False)
    leaf = build_worker_identity(has_dependents=False, captain=False)
    assert "必须调用 handoff" in upstream
    assert "接力契约 + 增量交代" in upstream
    assert "不必为交而交" not in upstream

    assert "不必为交而交" in leaf
    assert "接力契约 + 增量交代" in leaf
    assert "必须调用 handoff" not in leaf

    # Executor wires topology into the live system prompt (not just the helper).
    plan, _ = build_run_plan(
        [
            {"id": "arch", "role": "调研", "task": "查资料"},
            {
                "id": "impl",
                "role": "写手",
                "task": "成文",
                "depends_on": ["arch"],
            },
        ],
        id_prefix="t",
    )
    up_provider = _ContentProvider(["UP"])
    leaf_provider = _ContentProvider(["LEAF"])
    await _nesting_executor(plan, up_provider, lambda rid, d: _stub_subteam())(
        plan.by_id("t_arch"), {}
    )
    await _nesting_executor(plan, leaf_provider, lambda rid, d: _stub_subteam())(
        plan.by_id("t_impl"), {}
    )
    assert "必须调用 handoff" in up_provider.system_messages[0]
    assert "不必为交而交" in leaf_provider.system_messages[0]
    assert "必须调用 handoff" not in leaf_provider.system_messages[0]

    # Tool description covers both branches so it never fights either prompt.
    desc = HandoffTool().schema.description
    assert "接力契约 + 增量交代" in desc
    assert "必须" in desc
    assert "不必为交而交" in desc


def test_worker_identity_states_no_execution_capability():
    """能写≠能跑（能力闸门与交付诚实性）：执行类未装配时 identity 自述能力边界。

    can_execute=False（云端无沙箱 → registry 扣掉执行类）追加「执行环境未装配」块：
    能写脚本落盘、不能运行、不能生成需运行程序才产出的二进制文件、禁止谎称已运行/已生成；
    can_execute=True（默认）保持原样，本地/沙箱路径字节不变。
    """
    from agentcore.runtime.runs.executor_identities import build_worker_identity

    no_exec = build_worker_identity(has_dependents=False, can_execute=False)
    assert "本回合执行环境未装配" in no_exec
    assert "能】用写文件工具" in no_exec
    assert "不能】运行" in no_exec
    assert "二进制" in no_exec
    assert "已运行 / 已验证 / 已生成" in no_exec
    assert "未运行验证" in no_exec

    with_exec = build_worker_identity(has_dependents=False, can_execute=True)
    assert "本回合执行环境未装配" not in with_exec
    # 默认参数与显式 True 字节一致（不惊扰既有路径）。
    assert with_exec == build_worker_identity(has_dependents=False)


async def test_executor_passes_registry_capability_into_identity():
    """Executor 把 registry 能力事实接进 identity：空 registry（无 code_execute）→
    worker system prompt 带「执行环境未装配」自述。"""
    plan, _ = build_run_plan(
        [{"role": "工程师", "task": "写脚本"}],
        id_prefix="cap",
    )
    provider = _ContentProvider(["OUT"])
    await _nesting_executor(plan, provider, lambda rid, d: _stub_subteam())(
        plan.nodes[0], {}
    )
    assert "本回合执行环境未装配" in provider.system_messages[0]


async def test_worker_escalation_is_harvested_and_nonblocking():
    plan, _ = build_run_plan([{"role": "调研", "task": "查不清楚的事"}], id_prefix="t")
    reg = ToolRegistry()
    reg.register(EscalateTool())
    rounds = [
        [
            LLMChunk(
                delta_tool_calls=[
                    ToolCallDelta(
                        index=0,
                        id="c1",
                        function_name="escalate",
                        arguments_delta=(
                            '{"question": "用 Postgres 还是 MySQL?", '
                            '"assumption": "暂用 Postgres", "blocking": true}'
                        ),
                    )
                ]
            )
        ],
        [LLMChunk(delta_content="已按 Postgres 完成调研")],
    ]
    provider = _ScriptedRounds(rounds)
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=reg,
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="原始请求",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    state = res["t_1"]
    assert state.phase is RunPhase.COMPLETED  # non-blocking: it still delivered
    assert state.content == "已按 Postgres 完成调研"
    assert len(state.escalations) == 1
    esc = state.escalations[0]
    assert esc["question"] == "用 Postgres 还是 MySQL?"
    assert esc["assumption"] == "暂用 Postgres"
    assert esc["blocking"] is True


async def test_worker_escalation_emits_live_event_before_completion():
    # 升级实时可见: the executor wires the worker's escalate to a run-scoped RUN_ESCALATION
    # so the team UI surfaces it the INSTANT it is raised — well before the worker's node
    # completes (ordering proves "live", not a post-hoc harvest at run end).
    plan, _ = build_run_plan([{"role": "调研", "task": "查不清楚的事"}], id_prefix="t")
    reg = ToolRegistry()
    reg.register(EscalateTool())
    rounds = [
        [
            LLMChunk(
                delta_tool_calls=[
                    ToolCallDelta(
                        index=0,
                        id="c1",
                        function_name="escalate",
                        arguments_delta=(
                            '{"question": "用 Postgres 还是 MySQL?", '
                            '"assumption": "暂用 Postgres", "blocking": true}'
                        ),
                    )
                ]
            )
        ],
        [LLMChunk(delta_content="已按 Postgres 完成调研")],
    ]
    sink = EventSink()
    executor = build_agent_executor(
        plan=plan,
        llm=_ScriptedRounds(rounds),
        tools=reg,
        sink=sink,
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="原始请求",
        execution_id="e",
    )
    await WaveScheduler().run(plan, executor)
    sink.close()
    events = [e async for e in sink]
    types = [e.type for e in events]
    assert EventType.RUN_ESCALATION in types
    esc = next(e for e in events if e.type == EventType.RUN_ESCALATION)
    assert esc.payload["run_id"] == "t_1"
    assert esc.payload["question"] == "用 Postgres 还是 MySQL?"
    assert esc.payload["assumption"] == "暂用 Postgres"
    assert esc.payload["blocking"] is True
    # Live, not a harvest: the escalation surfaces strictly before the run finishes.
    assert types.index(EventType.RUN_ESCALATION) < types.index(EventType.RUN_COMPLETED)


async def test_worker_without_escalation_has_empty_list():
    plan, _ = build_run_plan([{"role": "A", "task": "做A"}], id_prefix="t")
    res = await WaveScheduler().run(plan, _executor(plan, _ContentProvider(["OUT"]), EventSink()))
    assert res["t_1"].escalations == []


async def test_escalate_tool_rejects_empty_question_and_acks_otherwise():
    tool = EscalateTool()
    bad = await tool.execute({"question": "  "}, _ctx())
    assert bad.success is False and "question" in (bad.error or "")
    # A valid escalation is acknowledged with a CONTINUE (non-terminal) result that
    # steers the worker to keep delivering — it is not a stop.
    ok = await tool.execute({"question": "Postgres 还是 MySQL?"}, _ctx())
    assert ok.success is True and ok.is_terminal is False
    assert "继续" in ok.output


async def test_escalate_invokes_on_escalate_callback_with_triple():
    # 升级实时可见: the tool hands the executor-provided live channel its (question,
    # assumption, blocking, kind) quadruple. An empty question is rejected BEFORE any emit.
    tool = EscalateTool()
    seen: list[tuple[str, str, bool, str]] = []
    ctx = replace(
        _ctx(), on_escalate=lambda q, a, b, k="normal": seen.append((q, a, b, k))
    )
    await tool.execute({"question": "  "}, ctx)
    assert seen == []  # rejected first, nothing surfaced
    await tool.execute({"question": "Q?", "assumption": "暂定 A", "blocking": True}, ctx)
    assert seen == [("Q?", "暂定 A", True, "normal")]


async def test_escalate_callback_failure_is_non_fatal():
    # The durable path (transcript → RunState.escalations) is unconditional, so a live-emit
    # hiccup must never sink the escalation or the worker — the tool still ACKs CONTINUE.
    def _boom(_q: str, _a: str, _b: bool, _k: str = "normal") -> None:
        raise RuntimeError("sink closed")

    ctx = replace(_ctx(), on_escalate=_boom)
    ok = await EscalateTool().execute({"question": "Q?"}, ctx)
    assert ok.success is True and ok.is_terminal is False


async def test_escalate_dep_kind_acks_with_replan_add_steer():
    # §2.4 变·worker 的「拉」(case b): escalate(kind="dep") flags a依赖缺口·卡在缺输入. It is a
    # non-blocking CONTINUE — the worker keeps going on its assumption while the CEO/lead补 a
    # producer at the boundary; the ACK names the replan(add) lever and the「绝不空等」rule.
    ok = await EscalateTool().execute(
        {"question": "缺错误返回结构才能写测试", "kind": "dep"}, _ctx()
    )
    assert ok.success is True and ok.is_terminal is False
    assert "replan" in ok.output
    assert "继续" in ok.output
