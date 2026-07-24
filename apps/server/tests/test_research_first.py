"""辩论开工卡「先多视角调研再辩」— 判据 / 回灌文案 / resume 分支。

2026-07-21：开工卡 offer/recommend 退役；回灌文案与 resume 分支保留。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentcore.core.types import ToolEffect
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.kickoff.research_first import (
    has_research_chain_evidence,
    hits_multi_lens_courtroom_triggers,
    research_first_tool_result,
    should_offer_research_first,
    should_recommend_research_first,
)
from agentcore.runtime.recover import SettledSuspension, recover_turn
from agentcore.runtime.skills import MULTI_LENS_COURTROOM_TRIGGERS
from agentcore.runtime.suspension import TeamPreviewSuspension
from agentcore.runtime.turn_state import TurnState
from agentcore.tools.builtin.motion_card import parse_motion_card


def _valid_card(**over: object) -> dict:
    card = {
        "motion": "该不该上四天工作制？",
        "form": "debate",
        "rationale": "双方对立轴清晰",
        "sides": [
            {"key": "pro", "name": "正方", "stance": "应推广"},
            {"key": "con", "name": "反方", "stance": "暂缓"},
        ],
        "fact_pointers": [],
    }
    card.update(over)
    parsed, err = parse_motion_card(card)
    assert parsed is not None and not err
    return parsed


def test_should_offer_research_first_retired_always_false():
    assert should_offer_research_first(None) is False
    assert should_offer_research_first([]) is False
    assert should_offer_research_first([], has_research_artifacts=False) is False
    assert should_offer_research_first([], has_research_artifacts=True) is False


def test_should_recommend_research_first_retired_always_false():
    assert should_recommend_research_first([], user_message="帮我做一场模拟法庭") is False
    assert should_recommend_research_first([], user_message="该不该上四天工作制？") is False


def test_hits_multi_lens_courtroom_triggers_shares_skills_constant():
    assert MULTI_LENS_COURTROOM_TRIGGERS
    for trigger in MULTI_LENS_COURTROOM_TRIGGERS:
        assert hits_multi_lens_courtroom_triggers(f"帮我做一场{trigger}") is True
    assert hits_multi_lens_courtroom_triggers("该不该上四天工作制？") is False
    assert hits_multi_lens_courtroom_triggers("") is False


def test_has_research_chain_evidence_preserves_old_offer_sources():
    assert has_research_chain_evidence([]) is False
    assert has_research_chain_evidence([], has_research_artifacts=True) is True
    entries_card = [
        {
            "kind": "run_completed",
            "payload": {
                "debrief": {"summary": "有争议", "motion_card": _valid_card()},
            },
        }
    ]
    assert has_research_chain_evidence(entries_card) is True
    entries_mlr = [
        {
            "kind": "tool_call",
            "payload": {
                "name": "delegate",
                "arguments": (
                    '{"playbook": "multi_lens_research", "playbook_args": {"topic": "T"}}'
                ),
                "success": True,
                "result": "done",
                "tool_call_id": "dc1",
                "run_id": "captain",
            },
        }
    ]
    assert has_research_chain_evidence(entries_mlr) is True
    failed = [
        {
            "kind": "tool_call",
            "payload": {
                "name": "delegate",
                "arguments": '{"playbook": "multi_lens_research"}',
                "success": False,
                "result": "err",
                "tool_call_id": "dc1",
                "run_id": "captain",
            },
        }
    ]
    assert has_research_chain_evidence(failed) is False


def test_research_first_tool_result_fills_motion_topic():
    text = research_first_tool_result(motion="该不该上四天工作制？", user_message="忽略我")
    assert "先多视角调研再辩" in text
    assert "请勿再次调用 debate" in text
    assert 'playbook="multi_lens_research"' in text
    assert '"topic": "该不该上四天工作制？"' in text
    assert "忽略我" not in text


def test_research_first_tool_result_falls_back_to_user_message():
    text = research_first_tool_result(motion="", user_message="帮我分析 LV 案")
    assert '"topic": "帮我分析 LV 案"' in text


@pytest.mark.asyncio
async def test_debate_resume_research_first_no_moderator():
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.interaction import InteractionRegistry
    from tests.test_kickoff_gate import _debate_tool

    registry = InteractionRegistry()
    sink = EventSink()

    async def _save(_frame):
        pass

    async def _drop(_mid):
        pass

    tool = _debate_tool(sink, registry, _save, _drop)
    tool._user_message = "直接开辩"

    async def _boom(*_a, **_k):
        raise AssertionError("must not run moderator on research_first")

    tool._run_moderator = _boom  # type: ignore[method-assign]
    tool.execute = _boom  # type: ignore[method-assign]

    result = await tool.resume_after_kickoff(
        decision=CheckpointDecision.RESEARCH_FIRST,
        note="",
        arguments={
            "motion": "该不该上四天工作制？",
            "form": "debate",
            "sides": [
                {"key": "pro", "name": "正方", "stance": "a"},
                {"key": "con", "name": "反方", "stance": "b"},
            ],
        },
    )
    assert result.effect is ToolEffect.CONTINUE
    assert result.success is True
    assert "先多视角调研再辩" in result.output
    assert 'playbook="multi_lens_research"' in result.output
    assert "该不该上四天工作制？" in result.output


@pytest.mark.asyncio
async def test_recover_research_first_on_delegate_kickoff_degrades_to_stop():
    """非辩论开工卡收到 research_first → 降级 STOP，不得静默 continue / 开做。"""
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.runs.plan import RunPlan

    sink = EventSink()
    suspension = TeamPreviewSuspension(
        message_id="m1",
        conversation_id="c1",
        user_id="u1",
        captain_run_id="cap",
        checkpoint_id="tp1",
        tool_call_id="dc1",
        base_system_prompt="",
        user_message="调研一下",
        plan=RunPlan(),
        workers=[
            {
                "run_id": "w1",
                "role": "调研",
                "task": "做A",
                "depends_on": [],
                "debate": False,
            }
        ],
        tools=[],
        primitive="delegate",
    )
    state = TurnState.from_journal([])

    stopped: list[str] = []

    class _FakeDelegate:
        async def resume_plan(self, *_a, **kwargs):
            stopped.append(kwargs.get("decision"))
            return SimpleNamespace(output="stopped", effect=ToolEffect.CONTINUE)

    settled = await recover_turn(
        state=state,
        sink=sink,
        delegate_tool=_FakeDelegate(),  # type: ignore[arg-type]
        execution_id="e1",
        suspension=suspension,
        decision=CheckpointDecision.RESEARCH_FIRST,
        note="",
    )
    assert isinstance(settled, SettledSuspension)
    assert stopped == [CheckpointDecision.STOP]
    resolved = [e for e in sink._history if e.type.value == "team_preview_resolved"]
    assert len(resolved) == 1
    assert resolved[0].payload["decision"] == "stop"
