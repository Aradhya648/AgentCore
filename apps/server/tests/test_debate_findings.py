"""红队 finding 台账 + 形态 profile 单测。"""

from __future__ import annotations

import asyncio

from agentcore.runtime.debate.findings import (
    apply_merge_plan,
    derive_gate,
    findings_from_attack_turns,
    mark_answered,
    mark_unanswered,
)
from agentcore.runtime.debate.form_profile import form_profile
from agentcore.runtime.debate.moderator import Moderator
from agentcore.runtime.debate.types import (
    DebateConfig,
    DebateForm,
    DebateSide,
    Finding,
    FindingSeverity,
    FindingStatus,
    RoundPolicy,
    SideTurn,
)
from tests.test_debate_moderator import (
    _CONVERGE,
    _config,
    _RecordingRunner,
    _red_team_sides,
    _run,
    _ScriptedLLM,
)


def test_form_profile_red_team_thorough_has_rebuttal_no_closing():
    cfg = _config(
        form=DebateForm.RED_TEAM,
        sides=_red_team_sides(),
        policy=RoundPolicy(max_rounds=5),
    )
    p = form_profile(cfg)
    assert p.unit == "finding"
    assert p.cross_exam is False
    assert p.closing is False
    assert p.has_rebuttal is True
    assert "rebuttal" in p.phases


def test_form_profile_red_team_quick_two_beats():
    cfg = _config(
        form=DebateForm.RED_TEAM,
        sides=_red_team_sides(),
        policy=RoundPolicy.quick(),
    )
    p = form_profile(cfg)
    assert p.has_rebuttal is False
    assert p.phases == ("attack", "merge", "defense")


def test_form_profile_debate_unchanged():
    p = form_profile(_config(policy=RoundPolicy(max_rounds=5)))
    assert p.unit == "side_turn"
    assert p.cross_exam is True
    assert p.closing is True


def test_findings_from_bullet_and_fallback():
    turns = [
        SideTurn(
            "red",
            "红队",
            "r1",
            "- [critical] 指向：令牌轮换 — 泄漏即长期可用\n- [minor] 指向：文档 — 缺运维手册",
            ok=True,
            beat="attack",
        )
    ]
    fs = findings_from_attack_turns(turns, round_no=1)
    assert len(fs) == 2
    assert fs[0].severity is FindingSeverity.CRITICAL
    assert fs[0].id == "r1-f1"


def test_merge_plan_prefers_keep_over_mis_merge():
    seeds = [
        Finding("a", FindingSeverity.MAJOR, "x", "r1", attack_run_id="1"),
        Finding("b", FindingSeverity.MAJOR, "y", "r2", attack_run_id="2"),
    ]
    # into 不存在 → 宁少合并，保留原样中 keep 子集
    out = apply_merge_plan(seeds, {"keep": ["a", "b"], "merges": [{"into": "ghost", "from": ["a"]}]})
    assert {f.id for f in out} == {"a", "b"}


def test_derive_gate_and_unanswered():
    fs = [
        Finding("f1", FindingSeverity.CRITICAL, "t", "r", status=FindingStatus.ESCALATED),
        Finding("f2", FindingSeverity.MAJOR, "t2", "r", status=FindingStatus.CLOSED),
    ]
    gate, must = derive_gate(fs)
    assert gate == "not_viable"
    assert must == ["f1"]
    unanswered = mark_unanswered(fs)
    assert all(f.status is FindingStatus.UNANSWERED for f in unanswered)
    answered = mark_answered(fs[:1], response_run_id="def1")
    assert answered[0].status is FindingStatus.ANSWERED
    assert answered[0].response_run_id == "def1"


def test_red_team_round_emits_findings_and_empty_closings():
    llm = _ScriptedLLM(judge_results=[_CONVERGE])
    runner = _RecordingRunner()
    result = _run(
        llm,
        runner,
        _config(
            form=DebateForm.RED_TEAM,
            sides=_red_team_sides(),
            policy=RoundPolicy(max_rounds=1),
        ),
    )
    assert result.closings == []
    assert result.rounds[0].findings
    assert result.brief.gate
    assert result.brief.risk_severities == {}
    # 攻击 → 回应 → 复攻（thorough）
    beats = [c["beat"] for c in runner.calls]
    assert "attack" in beats
    assert "defense" in beats
    assert "rebuttal" in beats


def test_roundtable_serial_thread_turns():
    rt = [DebateSide(key=k, name=k, stance=k) for k in ("a", "b", "c")]
    llm = _ScriptedLLM(judge_results=[_CONVERGE])
    runner = _RecordingRunner()
    result = asyncio.run(
        Moderator(provider=llm, model="m").run(
            DebateConfig(
                motion="圆桌命题",
                form=DebateForm.ROUNDTABLE,
                sides=rt,
                policy=RoundPolicy(max_rounds=1),
            ),
            run_round=runner,
        )
    )
    assert result.subtopics
    assert result.rounds[0].thread_turns
    assert all(c["beat"] == "thread" or c["beat"] == "crux" for c in runner.calls)
    # 串行：每次点名单方
    assert all(len(c["sides"]) == 1 for c in runner.calls)
