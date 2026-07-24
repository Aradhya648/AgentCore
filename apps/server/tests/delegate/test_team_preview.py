"""Unit tests for the thin team_preview gate (方案 A)."""

from __future__ import annotations

from types import SimpleNamespace

from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.coordination.session import (
    active_coordination,
    clear_active_coordination,
)
from agentcore.runtime.delegate.preview import (
    should_preview,
    skip_after_confirmed_ask,
    worker_rows,
)
from agentcore.runtime.delegate.steer import apply_steer
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.facts import TurnFactLog, current_fact_log
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunSpec
from agentcore.runtime.suspension import TeamPreviewSuspension, captain_transcript
from tests.delegate.conftest import Provider, ctx, tool_durable


def _plan(*nodes: RunSpec) -> RunPlan:
    plan = RunPlan()
    for n in nodes:
        plan.add(n)
    return plan


def test_should_preview_multi_worker():
    plan = _plan(
        RunSpec(run_id="r1", task="a", role="调研"),
        RunSpec(run_id="r2", task="b", role="撰写", depends_on=["r1"]),
    )
    assert should_preview(plan, finalize=False) is True
    assert should_preview(plan, finalize=True) is True


def test_should_preview_skips_solo_finalize():
    plan = _plan(RunSpec(run_id="r1", task="alone", role="写手"))
    assert should_preview(plan, finalize=True) is False
    assert should_preview(plan, finalize=False) is False


def test_should_preview_debate_marked_solo():
    plan = _plan(RunSpec(run_id="r1", task="辩", role="正方", stance="pro", round=1))
    assert should_preview(plan, finalize=True) is True


def test_skip_after_confirmed_ask():
    tool = SimpleNamespace(
        _sink=SimpleNamespace(
            execution_journal=lambda: [
                {"type": "checkpoint_required", "payload": {}},
                {"type": "checkpoint_resolved", "payload": {"decision": "continue"}},
            ]
        )
    )
    assert skip_after_confirmed_ask(tool) is True
    tool_nb = SimpleNamespace(
        _sink=SimpleNamespace(
            execution_journal=lambda: [{"type": "question_posted", "payload": {}}]
        )
    )
    assert skip_after_confirmed_ask(tool_nb) is False
    tool_empty = SimpleNamespace(_sink=SimpleNamespace(execution_journal=lambda: None))
    assert skip_after_confirmed_ask(tool_empty) is False


def test_skip_after_verbal_affirm_of_plan():
    """Prior-turn verbal「认可」after a collaboration plan outline skips kickoff."""
    history = [
        {"role": "user", "content": "讨论下协作结构"},
        {
            "role": "assistant",
            "content": "下面是完整协作方案：四路并行调研员 + 汇总，分工如下……",
        },
    ]
    tool = SimpleNamespace(
        _sink=SimpleNamespace(execution_journal=lambda: None),
        user_message="认可",
        history=history,
    )
    assert skip_after_confirmed_ask(tool) is True
    # Affirm without a prior plan outline → still show kickoff.
    tool_no_plan = SimpleNamespace(
        _sink=SimpleNamespace(execution_journal=lambda: None),
        user_message="认可",
        history=[{"role": "user", "content": "你好"}],
    )
    assert skip_after_confirmed_ask(tool_no_plan) is False
    # Long non-affirm message → still show kickoff even with a plan on screen.
    tool_long = SimpleNamespace(
        _sink=SimpleNamespace(execution_journal=lambda: None),
        user_message="认可，不过我想先改一下交付格式再开干",
        history=history,
    )
    assert skip_after_confirmed_ask(tool_long) is False


def test_worker_rows_shape():
    plan = _plan(
        RunSpec(run_id="r1", task="调研方案", role="调研"),
        RunSpec(run_id="r2", task="写", role="撰写", depends_on=["r1"], stance="con"),
    )
    rows = worker_rows(plan)
    assert rows[0]["role"] == "调研"
    assert rows[0]["debate"] is False
    assert rows[1]["depends_on"] == ["r1"]
    assert rows[1]["debate"] is True


def test_apply_steer_empty_roots_targets_all():
    plan = _plan(
        RunSpec(run_id="r1", task="a", role="A"),
        RunSpec(run_id="r2", task="b", role="B", depends_on=["r1"]),
    )
    apply_steer(plan, {}, set(), "请更简洁")
    assert "请更简洁" in (plan.by_id("r1").steer or "")
    assert "请更简洁" in (plan.by_id("r2").steer or "")


async def test_coordinate_team_preview_suspends_before_fork():
    """coordinate + team_preview: durable pause is on the CEO path before the fork.

    CEO gets SUSPEND (so message_end(paused) / ResumePrompt can fire); no background
    coordination session is armed until the user CONTINUEs.
    """
    clear_active_coordination()
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list[TeamPreviewSuspension] = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    t = tool_durable(Provider(["AOUT", "BOUT"]), sink, registry, _save, _drop)
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
        # Default coordinate=True (≥2 workers) — must NOT fork before preview settles.
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

    assert result.effect is ToolEffect.SUSPEND
    assert "团队已启动" not in (result.output or "")
    assert active_coordination("e") is None
    assert len(saved) == 1
    assert isinstance(saved[0], TeamPreviewSuspension)
    assert len(saved[0].workers) == 2
    assert any(e.type is EventType.TEAM_PREVIEW_REQUIRED for e in sink._history)
    clear_active_coordination()


async def test_team_preview_continue_then_arms_coordination():
    """After durable team_preview CONTINUE, resume_plan(coordinate=True) arms the background."""
    import asyncio

    clear_active_coordination()
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list[TeamPreviewSuspension] = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    t = tool_durable(Provider(["AOUT", "BOUT"]), sink, registry, _save, _drop)
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
        pause = await t.execute(
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

    assert pause.effect is ToolEffect.SUSPEND
    frame = saved[0]
    resumed = await t.resume_plan(
        frame.plan,
        dict(frame.completed),
        decision=CheckpointDecision.CONTINUE,
        note="",
        checkpoint_run_ids=frame.checkpoint_run_ids,
        execution_id="e",
        coordinate=True,
    )
    assert resumed.success is True
    assert "团队已启动" in resumed.output
    session = active_coordination("e")
    assert session is not None and session.drive_task is not None
    await asyncio.wait_for(session.drive_task, timeout=10)
    clear_active_coordination("e")


async def test_kickoff_frame_captures_batch_coordination_and_fresh_tool_restores():
    """开工卡帧携带 coordination/team_brief/seed_notes；全新工具实例恢复后墙生效。

    真 bug（2026-07-20 P2 手驱真跑抓获）：挂起点在 setup_note_wall 之前，这三样只活在
    DelegateTool 实例上；耐久恢复走全新实例（_coordination 缺省 none），不随帧回灌则
    wall 批降级 → worker 被剥便签三件套、CEO 预贴便签永久丢失。
    """
    clear_active_coordination()
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list[TeamPreviewSuspension] = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    t = tool_durable(Provider(["AOUT", "BOUT"]), sink, registry, _save, _drop)
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
        pause = await t.execute(
            {
                "tasks": [
                    {"role": "观察员", "task": "做A"},
                    {"role": "撰稿人", "task": "做B"},
                ],
                "coordination": "wall",
                "team_brief": "统一用中文交付",
                "seed_notes": [{"kind": "heads_up", "text": "接口用 REST"}],
            },
            ctx(),
        )
    finally:
        captain_transcript.reset(ct_token)
        current_fact_log.reset(fl_token)

    assert pause.effect is ToolEffect.SUSPEND
    frame = saved[0]
    # 帧捕获批次协作参数，且 JSON 往返存活（耐久恢复走 suspension_from_json）。
    assert frame.coordination == "wall"
    assert frame.team_brief == "统一用中文交付"
    assert frame.seed_notes == [{"kind": "heads_up", "text": "接口用 REST"}]
    from agentcore.runtime.suspension import suspension_from_json

    rehydrated = suspension_from_json(frame.to_json())
    assert rehydrated.coordination == "wall"

    # 全新工具实例（模拟耐久恢复：_coordination 缺省 none）+ 帧回灌 → 墙生效。
    sink2 = EventSink()
    t2 = tool_durable(Provider(["AOUT", "BOUT"]), sink2, InteractionRegistry(), _save, _drop)
    assert t2._coordination == "none"
    resumed = await t2.resume_plan(
        frame.plan,
        {},
        decision=CheckpointDecision.CONTINUE,
        note="",
        checkpoint_run_ids=frame.checkpoint_run_ids,
        execution_id="e",
        coordinate=False,  # 经典阻塞，便于同步断言
        apply_kickoff_grant=True,
        coordination=rehydrated.coordination,
        team_brief=rehydrated.team_brief,
        seed_notes=list(rehydrated.seed_notes),
    )
    assert resumed.success is True
    assert t2._coordination == "wall"
    assert t2._team_brief == "统一用中文交付"
    # CEO 预贴便签在恢复驱动里补种上墙（挂起时从未上过墙）。
    seeded = [
        e
        for e in sink2._history
        if e.type is EventType.TEAM_NOTE_POSTED and e.payload.get("source") == "ceo"
    ]
    assert len(seeded) == 1
    assert "接口用 REST" in seeded[0].payload.get("text", "")
    clear_active_coordination()
