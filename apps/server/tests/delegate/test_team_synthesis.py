"""CEO 协调模式 Phase 1：确定性团队进展摘要单元测试。"""

from agentcore.runtime.delegate.team_synthesis import (
    build_team_synthesis_preview,
    maybe_emit_team_synthesis_preview,
    worker_output_blurb,
)
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState


def test_solo_worker_returns_none():
    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="solo", role="分析师")])
    completed = {
        "w1": RunState(phase=RunPhase.COMPLETED, content="done", debrief={"summary": "ok"}),
    }
    assert build_team_synthesis_preview(plan, completed, execution_id="e1") is None


def test_multi_worker_partial_progress():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="w1", task="db", role="数据库分析"),
            RunSpec(run_id="w2", task="api", role="API 分析"),
            RunSpec(run_id="w3", task="fe", role="前端分析"),
            RunSpec(run_id="w4", task="sec", role="安全检查"),
        ]
    )
    completed = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="长文…",
            debrief={"summary": "索引策略已定"},
        ),
        "w2": RunState(
            phase=RunPhase.COMPLETED,
            content="API 草案完成，覆盖鉴权与分页。",
        ),
    }
    payload = build_team_synthesis_preview(plan, completed, execution_id="exec-1")
    assert payload is not None
    assert payload["execution_id"] == "exec-1"
    assert payload["completed"] == 2
    assert payload["total"] == 4
    assert payload["in_progress"] is True
    assert payload["headline"].startswith("已完成 2/4：")
    assert "✅ 数据库分析" in payload["headline"]
    assert "✅ API 分析" in payload["headline"]
    assert "⏳ 前端分析" in payload["headline"]
    assert "⏳ 安全检查" in payload["headline"]
    assert "· 数据库分析：索引策略已定" in payload["text"]
    assert "· API 分析：API 草案完成" in payload["text"]
    statuses = {w["run_id"]: w["status"] for w in payload["workers"]}
    assert statuses == {
        "w1": "completed",
        "w2": "completed",
        "w3": "pending",
        "w4": "pending",
    }


def test_all_completed_clears_in_progress():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="a", task="t", role="A"),
            RunSpec(run_id="b", task="t", role="B"),
        ]
    )
    completed = {
        "a": RunState(phase=RunPhase.COMPLETED, debrief={"summary": "a ok"}),
        "b": RunState(phase=RunPhase.COMPLETED, debrief={"summary": "b ok"}),
    }
    payload = build_team_synthesis_preview(plan, completed, execution_id="e")
    assert payload is not None
    assert payload["completed"] == 2
    assert payload["in_progress"] is False
    assert "⏳" not in payload["headline"]


def test_failed_worker_marked():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="a", task="t", role="A"),
            RunSpec(run_id="b", task="t", role="B"),
        ]
    )
    completed = {
        "a": RunState(phase=RunPhase.COMPLETED, debrief={"summary": "ok"}),
        "b": RunState(phase=RunPhase.FAILED, error="timeout"),
    }
    payload = build_team_synthesis_preview(plan, completed, execution_id="e")
    assert payload is not None
    assert payload["completed"] == 1
    assert "❌ B" in payload["headline"]
    assert "· B：失败：timeout" in payload["text"]


def test_worker_output_blurb_cancelled_is_stopped():
    assert worker_output_blurb(RunState(phase=RunPhase.CANCELLED)) == "已停止"


def test_worker_output_blurb_prefers_debrief():
    state = RunState(
        phase=RunPhase.COMPLETED,
        content="全文很长不应优先",
        debrief={"summary": "一句话结论"},
    )
    assert worker_output_blurb(state) == "一句话结论"


def test_maybe_emit_skips_solo_and_emits_multi():
    sink = EventSink()
    solo = RunPlan(nodes=[RunSpec(run_id="w1", task="t", role="Solo")])
    maybe_emit_team_synthesis_preview(
        sink,
        solo,
        {"w1": RunState(phase=RunPhase.COMPLETED, content="x")},
        execution_id="e",
    )
    assert not any(e.type is EventType.TEAM_SYNTHESIS_PREVIEW for e in sink._history)

    multi = RunPlan(
        nodes=[
            RunSpec(run_id="w1", task="t", role="A"),
            RunSpec(run_id="w2", task="t", role="B"),
        ]
    )
    maybe_emit_team_synthesis_preview(
        sink,
        multi,
        {"w1": RunState(phase=RunPhase.COMPLETED, debrief={"summary": "done"})},
        execution_id="e2",
    )
    events = [e for e in sink._history if e.type is EventType.TEAM_SYNTHESIS_PREVIEW]
    assert len(events) == 1
    assert events[0].payload["completed"] == 1
    assert events[0].payload["total"] == 2
