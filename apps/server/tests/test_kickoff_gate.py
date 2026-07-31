"""Orchestration-layer kickoff gate — shared rules for delegate + debate + ask_user."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agentcore.core.types import (
    AutonomyPolicy,
    CommandAxis,
    FileWriteAxis,
    HostAxis,
    PermissionAxes,
    TeamKickoffAxis,
    ToolEffect,
    recipe_to_axes,
)

# Explicit kickoff-command axes for授/开工卡 (no longer a built-in recipe).
_KICKOFF_RULES = PermissionAxes(
    FileWriteAxis.SESSION,
    CommandAxis.KICKOFF,
    TeamKickoffAxis.RULES,
    HostAxis.ASK,
)
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.delegate.preview import should_kickoff as delegate_should_kickoff
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.facts import TurnFactLog, current_fact_log
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.runtime.kickoff import (
    debate_kickoff_summary,
    needs_capability_auth,
    should_kickoff,
    should_preview_delegate_plan,
    skip_after_confirmed_ask,
    user_confirmed_kickoff_decisions,
)
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunSpec
from agentcore.runtime.suspension import TeamPreviewSuspension, captain_transcript
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.builtin.debate import DebateTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.delegate.conftest import Provider, ctx, tool_durable


def _plan(*nodes: RunSpec) -> RunPlan:
    plan = RunPlan()
    for n in nodes:
        plan.add(n)
    return plan


async def test_ask_user_allows_after_verbal_affirm():
    """User「认可」after a collaboration plan → still may short-ask (no verbal skip)."""
    history = [
        {"role": "user", "content": "讨论下协作结构"},
        {
            "role": "assistant",
            "content": "完整协作方案：四路并行调研员 + 汇总，分工如下……",
        },
    ]
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c1",
        timeout_seconds=1.0,
        user_message="认可",
        history=history,
    )
    assert user_confirmed_kickoff_decisions(tool) is False
    result = await tool.execute(
        {"message": "交付形态再确认一下？", "assumptions": ["按四路并行开干"]},
        ToolContext(
            execution_id="e",
            run_id="s",
            agent_id="a",
            backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
            user_id="u",
        ),
    )
    assert "勿再开开工提案卡" not in (result.error or "")


async def test_ask_user_allows_after_team_preview_resolved():
    """team_preview_resolved 不再拒 ask_user 短问（开工提案拒调已拆）。"""
    sink = EventSink()
    sink.seed_journal(
        [
            {
                "type": EventType.TEAM_PREVIEW_REQUIRED.value,
                "payload": {"checkpoint_id": "tp1"},
                "timestamp": "t0",
            },
            {
                "type": EventType.TEAM_PREVIEW_RESOLVED.value,
                "payload": {"checkpoint_id": "tp1", "decision": "continue"},
                "timestamp": "t1",
            },
        ]
    )
    tool = AskUserTool(
        sink=sink,
        conversation_id="c1",
        timeout_seconds=1.0,
        user_message="继续",
    )
    # Gate predicate still ignores team_preview_resolved (incremental delegate must kickoff).
    assert user_confirmed_kickoff_decisions(tool) is False
    assert skip_after_confirmed_ask(tool) is False

    result = await tool.execute(
        {"message": "交付形态再确认一下？"},
        ToolContext(
            execution_id="e",
            run_id="s",
            agent_id="a",
            backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
            user_id="u",
        ),
    )
    # Without durable frame → explicit fail path may apply; must NOT be kickoff-refuse.
    assert "勿再开开工提案卡" not in (result.error or "")


def test_skip_after_confirmed_ask_ignores_team_preview_resolved():
    """B3: gate skip side must NOT treat team_preview_resolved as settled ask."""
    tool = SimpleNamespace(
        _sink=SimpleNamespace(
            execution_journal=lambda: [
                {"type": "team_preview_required", "payload": {}},
                {"type": "team_preview_resolved", "payload": {"decision": "continue"}},
            ]
        )
    )
    assert skip_after_confirmed_ask(tool) is False
    assert user_confirmed_kickoff_decisions(tool) is False


def test_full_auto_releases_plan_half():
    """full_auto skips the kickoff card even when plan_preview would show."""
    assert (
        should_kickoff(
            plan_preview=True,
            local_gate=True,
            axes=recipe_to_axes(AutonomyPolicy.MANAGED),
        )
        is False
    )
    assert (
        should_kickoff(
            plan_preview=True,
            local_gate=False,
            axes=recipe_to_axes(AutonomyPolicy.MANAGED),
        )
        is False
    )


def test_capability_auth_three_tiers():
    assert needs_capability_auth(local_gate=True, axes=_KICKOFF_RULES) is True
    assert needs_capability_auth(local_gate=True, axes=recipe_to_axes(AutonomyPolicy.CAUTIOUS)) is False
    assert needs_capability_auth(local_gate=True, axes=recipe_to_axes(AutonomyPolicy.MANAGED)) is False
    assert needs_capability_auth(local_gate=False, axes=_KICKOFF_RULES) is False


def test_delegate_trigger_rules_unchanged():
    multi = _plan(
        RunSpec(run_id="r1", task="a", role="调研"),
        RunSpec(run_id="r2", task="b", role="撰写", depends_on=["r1"]),
    )
    solo = _plan(RunSpec(run_id="r1", task="alone", role="写手"))
    assert should_preview_delegate_plan(multi, finalize=False) is True
    assert should_preview_delegate_plan(solo, finalize=True) is False
    assert (
        delegate_should_kickoff(
            multi, finalize=False, local_gate=False, axes=_KICKOFF_RULES
        )
        is True
    )
    assert (
        delegate_should_kickoff(
            multi, finalize=False, local_gate=False, axes=recipe_to_axes(AutonomyPolicy.MANAGED)
        )
        is False
    )
    assert (
        delegate_should_kickoff(
            solo, finalize=True, local_gate=True, axes=_KICKOFF_RULES
        )
        is True
    )  # capability half only


def test_checkpoint_after_yields_plan_preview_half():
    """B2: checkpoint_after in batch → plan half off; capability half independent."""
    with_cp = _plan(
        RunSpec(run_id="r1", task="提纲", role="写作", checkpoint_after=True),
        RunSpec(run_id="r2", task="全文", role="写作", depends_on=["r1"]),
    )
    assert should_preview_delegate_plan(with_cp, finalize=False) is False
    # Capability auth still drives kickoff when local gate is on.
    assert (
        should_kickoff(
            plan_preview=False,
            local_gate=True,
            axes=_KICKOFF_RULES,
        )
        is True
    )
    assert (
        delegate_should_kickoff(
            with_cp, finalize=False, local_gate=True, axes=_KICKOFF_RULES
        )
        is True
    )
    # No local gate + checkpoint batch → no kickoff card at all.
    assert (
        delegate_should_kickoff(
            with_cp, finalize=False, local_gate=False, axes=_KICKOFF_RULES
        )
        is False
    )
    # Debate-marked node without checkpoint still previews.
    debate_only = _plan(RunSpec(run_id="r1", task="辩", role="正方", stance="应推广"))
    assert should_preview_delegate_plan(debate_only, finalize=False) is True
    # Debate-marked + checkpoint_after → plan half still yields.
    debate_cp = _plan(
        RunSpec(run_id="r1", task="辩", role="正方", stance="应推广", checkpoint_after=True)
    )
    assert should_preview_delegate_plan(debate_cp, finalize=False) is False


def test_debate_kickoff_summary_shape():
    from agentcore.runtime.debate import DebateConfig, DebateForm, DebateSide, RoundPolicy

    config = DebateConfig(
        motion="该不该上四天工作制？",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide(key="pro", name="正方", stance="应推广"),
            DebateSide(key="con", name="反方", stance="暂缓"),
        ],
        policy=RoundPolicy(thorough=True, max_rounds=5),
    )
    args = {
        "motion": config.motion,
        "form": "debate",
        "sides": [
            {"key": "pro", "name": "正方", "stance": "应推广"},
            {"key": "con", "name": "反方", "stance": "暂缓"},
        ],
        "thorough": True,
    }
    summary = debate_kickoff_summary(config, arguments=args)
    assert summary.primitive == "debate"
    assert summary.motion == config.motion
    assert len(summary.sides) == 2
    assert summary.max_rounds == 5
    assert summary.workers == []
    card = summary.card_payload()
    assert card["primitive"] == "debate"
    assert card["thorough"] is True


def _debate_tool(
    sink: EventSink,
    registry: InteractionRegistry,
    save,
    drop,
    *,
    permission_axes=None,
) -> DebateTool:
    if permission_axes is None:
        permission_axes = _KICKOFF_RULES
    return DebateTool(
        llm=Provider([]),
        sink=sink,
        system_prompt="sys",
        user_message="辩一下",
        tools=ToolRegistry(),
        base_tool_context=ctx(),
        conversation_id="c",
        ambient_armed=True,
        message_id="m1",
        suspension_saver=save,
        suspension_deleter=drop,
        permission_axes=permission_axes,
        registry=registry,
        captain_run_id="ceo",
    )


async def test_debate_top_level_must_kickoff():
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list[TeamPreviewSuspension] = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    tool = _debate_tool(sink, registry, _save, _drop)
    transcript = [
        LLMMessage(role="user", content="辩一下"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_debate",
                    function=ToolCallFunction(name="debate", arguments="{}"),
                )
            ],
        ),
    ]
    log = TurnFactLog()
    fl_token = current_fact_log.set(log)
    ct_token = captain_transcript.set(transcript)
    try:
        result = await tool.execute(
            {
                "motion": "该不该上四天工作制？",
                "form": "debate",
                "sides": [
                    {"key": "pro", "name": "正方", "stance": "应推广"},
                    {"key": "con", "name": "反方", "stance": "暂缓"},
                ],
                "thorough": True,
            },
            ctx(),
        )
    finally:
        captain_transcript.reset(ct_token)
        current_fact_log.reset(fl_token)

    assert result.effect is ToolEffect.SUSPEND
    assert len(saved) == 1
    assert saved[0].primitive == "debate"
    assert saved[0].motion.startswith("该不该")
    # 开工卡 research_first 键已退役：不再 offer
    assert saved[0].offer_research_first is False
    assert any(e.type is EventType.TEAM_PREVIEW_REQUIRED for e in sink._history)
    required = next(e for e in sink._history if e.type is EventType.TEAM_PREVIEW_REQUIRED)
    assert required.payload["primitive"] == "debate"
    assert required.payload.get("offer_research_first") is not True
    # Must pause before debate.started (no moderator run_started yet).
    assert not any(
        e.type is EventType.RUN_STARTED and str(e.payload.get("run_id", "")).startswith("debate_")
        for e in sink._history
    )


async def test_debate_full_auto_skips_kickoff():
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    tool = _debate_tool(
        sink, registry, _save, _drop, permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED)
    )
    # skip_kickoff path isn't what we test — full_auto must not suspend before moderator.
    # Without LLM we can't finish moderator; patch _run_moderator.
    async def _fake_run(config, usage_metadata):
        return SimpleNamespace(
            tool_call_id="",
            success=True,
            output="ok",
            effect=ToolEffect.CONTINUE,
            metadata={},
        )

    tool._run_moderator = _fake_run  # type: ignore[method-assign]
    result = await tool.execute(
        {
            "motion": "命题",
            "form": "debate",
            "sides": [
                {"key": "pro", "name": "正方", "stance": "a"},
                {"key": "con", "name": "反方", "stance": "b"},
            ],
        },
        ctx(),
    )
    assert result.effect is not ToolEffect.SUSPEND
    assert saved == []


async def test_debate_resume_stop_continue_adjust():
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    tool = _debate_tool(sink, registry, _save, _drop)
    args = {
        "motion": "原命题",
        "form": "debate",
        "sides": [
            {"key": "pro", "name": "正方", "stance": "a"},
            {"key": "con", "name": "反方", "stance": "b"},
        ],
    }

    stop = await tool.resume_after_kickoff(
        decision=CheckpointDecision.STOP, note="算了", arguments=args
    )
    assert "停止" in stop.output or "算了" in stop.output

    captured: list[dict] = []

    async def _capture_execute(arguments, context, *, skip_kickoff=False):
        captured.append({"arguments": dict(arguments), "skip_kickoff": skip_kickoff})
        return SimpleNamespace(
            tool_call_id="",
            success=True,
            output="ran",
            effect=ToolEffect.CONTINUE,
        )

    tool.execute = _capture_execute  # type: ignore[method-assign]

    cont = await tool.resume_after_kickoff(
        decision=CheckpointDecision.CONTINUE, note="", arguments=args
    )
    assert cont.output == "ran"
    assert captured[-1]["skip_kickoff"] is True
    assert captured[-1]["arguments"]["motion"] == "原命题"
    assert "_kickoff_ask" not in captured[-1]["arguments"]

    cont_note = await tool.resume_after_kickoff(
        decision=CheckpointDecision.CONTINUE,
        note="最关心成本谁买单",
        arguments=args,
    )
    assert cont_note.output == "ran"
    assert captured[-1]["arguments"]["motion"] == "原命题"
    assert captured[-1]["arguments"]["_kickoff_ask"] == "最关心成本谁买单"

    # ADJUST 历史语义：与 CONTINUE+note 同构（嘱咐注入），不再覆写 motion。
    adj = await tool.resume_after_kickoff(
        decision=CheckpointDecision.ADJUST, note="改成新命题", arguments=args
    )
    assert adj.output == "ran"
    assert captured[-1]["arguments"]["motion"] == "原命题"
    assert captured[-1]["arguments"]["_kickoff_ask"] == "改成新命题"


async def test_delegate_full_auto_multi_skips_card():
    """Regression: full_auto + ≥2 workers no longer pauses for plan half."""
    from agentcore.runtime.coordination.session import clear_active_coordination

    clear_active_coordination()
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    t = tool_durable(Provider(["AOUT", "BOUT"]), sink, registry, _save, _drop)
    t._permission_axes = recipe_to_axes(AutonomyPolicy.MANAGED)
    transcript = [
        LLMMessage(role="user", content="原始请求"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_del",
                    function=ToolCallFunction(name="delegate", arguments="{}"),
                )
            ],
        ),
    ]
    log = TurnFactLog()
    fl_token = current_fact_log.set(log)
    ct_token = captain_transcript.set(transcript)
    try:
        result = await t.execute(
            {
                "tasks": [
                    {"role": "研究员", "task": "做A"},
                    {"role": "写手", "task": "做B"},
                ],
            },
            ctx(),
        )
    finally:
        captain_transcript.reset(ct_token)
        current_fact_log.reset(fl_token)

    assert result.effect is not ToolEffect.SUSPEND
    assert saved == []
    clear_active_coordination()
