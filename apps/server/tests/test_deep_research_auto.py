"""深度研究自治 — helper、ceo_format 指引分叉、debate 开赛卡放行域与上限降级。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agentcore.core.types import AutonomyPolicy, recipe_to_axes, ToolEffect
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.deep_research_auto import (
    AUTO_DEBATE_SESSION_LIMIT,
    deep_research_auto_active,
    may_auto_debate,
    tool_may_auto_debate,
)
from agentcore.runtime.delegate.ceo_format import (
    format_for_ceo,
    motion_cards_block,
)
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.facts import TurnFactLog, current_fact_log
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.runtime.kickoff import needs_capability_auth, should_kickoff
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from agentcore.runtime.suspension import captain_transcript
from agentcore.tools.builtin.debate import DebateTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.delegate.conftest import Provider, tool


def _valid_card() -> dict:
    return {
        "motion": "一审判决是否过重",
        "sides": [
            {"key": "pro", "name": "正方", "stance": "支持一审判决正确"},
            {"key": "con", "name": "反方", "stance": "认为判赔过重"},
        ],
        "fact_pointers": ["#r1"],
        "rationale": "双方对赔偿数额的法律适用存在根本对立。",
        "form": "debate",
    }


# ── helper 蕴含关系 ───────────────────────────────────────────────


def test_helper_flag_or_full_trust():
    managed = recipe_to_axes(AutonomyPolicy.MANAGED)
    write_code = recipe_to_axes(AutonomyPolicy.WRITE_CODE)
    cautious = recipe_to_axes(AutonomyPolicy.CAUTIOUS)
    assert deep_research_auto_active(deep_research_auto=True) is True
    assert deep_research_auto_active(permission_axes=managed) is True
    assert deep_research_auto_active(
        deep_research_auto=False,
        permission_axes=write_code,
    ) is False
    assert deep_research_auto_active(permission_axes=cautious) is False


def test_helper_may_auto_debate_respects_session_cap():
    assert (
        may_auto_debate(deep_research_auto=True, auto_debate_count=0) is True
    )
    assert (
        may_auto_debate(
            deep_research_auto=True,
            auto_debate_count=AUTO_DEBATE_SESSION_LIMIT,
        )
        is False
    )
    assert (
        may_auto_debate(
            permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
            auto_debate_count=0,
        )
        is True
    )
    assert (
        may_auto_debate(
            permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
            auto_debate_count=1,
        )
        is False
    )


# ── ceo_format 消费指引两态 ───────────────────────────────────────


def test_motion_cards_block_default_vs_auto_guidance():
    products = [
        {
            "role": "汇总",
            "run_id": "w1",
            "motion_card": _valid_card(),
        }
    ]
    default = motion_cards_block(products, auto_adopt=False)
    assert "消费指引·默认模式" in default
    assert "不要】直接调用 debate" in default or "不要直接调用 debate" in default
    assert "深度研究自治" not in default

    auto = motion_cards_block(products, auto_adopt=True)
    assert "消费指引·深度研究自治" in auto
    assert "可直接调 debate" in auto
    assert "不得装观点" in auto
    assert "不要】直接调用 debate" not in auto


def test_format_for_ceo_auto_adopt_guidance_when_flag_under_cap():
    t = tool(Provider([]))
    t._base_tool_context.deep_research_auto = True
    t._base_tool_context.deep_research_auto_debate_count = 0
    assert tool_may_auto_debate(t) is True
    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="汇总", role="汇总")])
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="分析",
            debrief={"summary": "争议", "motion_card": _valid_card()},
        )
    }
    out = format_for_ceo(t, plan, results)
    assert "消费指引·深度研究自治" in out
    assert "可直接调 debate" in out
    assert "本回合不要直接调用 debate" not in out


def test_format_for_ceo_falls_back_when_over_cap():
    t = tool(Provider([]))
    t._base_tool_context.deep_research_auto = True
    t._base_tool_context.deep_research_auto_debate_count = 1
    assert tool_may_auto_debate(t) is False
    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="汇总", role="汇总")])
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="分析",
            debrief={"summary": "争议", "motion_card": _valid_card()},
        )
    }
    out = format_for_ceo(t, plan, results)
    assert "消费指引·默认模式" in out
    assert "不要直接调用 debate" in out or "不要】直接调用 debate" in out


def test_format_for_ceo_full_trust_auto_guidance_no_regression_under_cap():
    t = tool(Provider([]))
    t._permission_axes = recipe_to_axes(AutonomyPolicy.MANAGED)
    t._base_tool_context.deep_research_auto_debate_count = 0
    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="汇总", role="汇总")])
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="分析",
            debrief={"summary": "争议", "motion_card": _valid_card()},
        )
    }
    out = format_for_ceo(t, plan, results)
    assert "消费指引·深度研究自治" in out


# ── 开赛卡放行域 ─────────────────────────────────────────────────


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c-dra",
        **kwargs,
    )


def _debate_tool(
    *,
    permission_axes=None,
    deep_research_auto: bool = False,
    debate_count: int = 0,
) -> tuple[DebateTool, list, EventSink]:
    if permission_axes is None:
        permission_axes = recipe_to_axes(AutonomyPolicy.WRITE_CODE)
    registry = InteractionRegistry()
    sink = EventSink()
    saved: list = []

    async def _save(frame):
        saved.append(frame)

    async def _drop(_mid):
        pass

    base = _ctx(
        deep_research_auto=deep_research_auto,
        deep_research_auto_debate_count=debate_count,
    )
    tool = DebateTool(
        llm=Provider([]),
        sink=sink,
        system_prompt="sys",
        user_message="辩一下",
        tools=ToolRegistry(),
        base_tool_context=base,
        conversation_id="c-dra",
        ambient_armed=True,
        message_id="m1",
        suspension_saver=_save,
        suspension_deleter=_drop,
        permission_axes=permission_axes,
        registry=registry,
        captain_run_id="ceo",
    )
    return tool, saved, sink


_DEBATE_ARGS = {
    "motion": "该不该上四天工作制？",
    "form": "debate",
    "sides": [
        {"key": "pro", "name": "正方", "stance": "应推广"},
        {"key": "con", "name": "反方", "stance": "暂缓"},
    ],
}


async def test_debate_flag_skips_kickoff_under_cap():
    tool, saved, sink = _debate_tool(deep_research_auto=True, debate_count=0)

    async def _fake_run(config, usage_metadata):
        return SimpleNamespace(
            tool_call_id="",
            success=True,
            output="ok",
            effect=ToolEffect.CONTINUE,
            metadata={},
        )

    tool._run_moderator = _fake_run  # type: ignore[method-assign]
    result = await tool.execute(_DEBATE_ARGS, tool._base_tool_context)
    assert result.effect is not ToolEffect.SUSPEND
    assert saved == []
    assert not any(e.type is EventType.TEAM_PREVIEW_REQUIRED for e in sink._history)
    # in-memory count bumped (DB may be unavailable in unit tests)
    assert tool._base_tool_context.deep_research_auto_debate_count >= 1


async def test_debate_flag_restores_kickoff_over_cap():
    tool, saved, sink = _debate_tool(deep_research_auto=True, debate_count=1)
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
        result = await tool.execute(_DEBATE_ARGS, tool._base_tool_context)
    finally:
        captain_transcript.reset(ct_token)
        current_fact_log.reset(fl_token)
    assert result.effect is ToolEffect.SUSPEND
    assert len(saved) == 1
    assert any(e.type is EventType.TEAM_PREVIEW_REQUIRED for e in sink._history)


async def test_debate_full_trust_still_skips_over_cap():
    """full_trust 不因计数上限开始挂卡（行为不回归）。"""
    tool, saved, _sink = _debate_tool(
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED), debate_count=1
    )

    async def _fake_run(config, usage_metadata):
        return SimpleNamespace(
            tool_call_id="",
            success=True,
            output="ok",
            effect=ToolEffect.CONTINUE,
            metadata={},
        )

    tool._run_moderator = _fake_run  # type: ignore[method-assign]
    result = await tool.execute(_DEBATE_ARGS, tool._base_tool_context)
    assert result.effect is not ToolEffect.SUSPEND
    assert saved == []


def test_flag_does_not_waive_capability_auth_or_plan_kickoff():
    """只放行 debate 开赛卡；能力审批 / 计划半 kickoff 规则不变。"""
    assert needs_capability_auth(
        local_gate=True, axes=recipe_to_axes(AutonomyPolicy.WRITE_CODE)
    ) is True
    assert (
        should_kickoff(
            plan_preview=True,
            local_gate=True,
            axes=recipe_to_axes(AutonomyPolicy.WRITE_CODE),
        )
        is True
    )
    # managed 仍全跳（既有 full_trust 行为）
    assert (
        should_kickoff(
            plan_preview=True,
            local_gate=True,
            axes=recipe_to_axes(AutonomyPolicy.MANAGED),
        )
        is False
    )
