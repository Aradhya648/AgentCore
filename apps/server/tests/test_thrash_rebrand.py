"""Thrash rebrand admission: cold similar task rejected; continue_from / force pass."""

from __future__ import annotations

from agentcore.runtime.coordination.thrash import (
    ThrashRecord,
    clear_thrash_registry,
    find_thrash_collision,
    is_thrashing_run_state,
    note_thrashing_worker,
    recent_thrash_records,
    thrash_reject_message,
)
from agentcore.runtime.engine.ceiling import CEILING_BACKSTOP_SOURCE
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import Deliverable, RunSpec, RunState


def _plan(*nodes: RunSpec) -> RunPlan:
    plan = RunPlan()
    for n in nodes:
        plan.add(n)
    return plan


def setup_function() -> None:
    clear_thrash_registry()


def test_is_thrashing_run_state_detects_ceiling_backstop():
    clean = RunState(escalations=[])
    assert not is_thrashing_run_state(clean)
    thrash = RunState(
        escalations=[{"source": CEILING_BACKSTOP_SOURCE, "question": "打转"}]
    )
    assert is_thrashing_run_state(thrash)


def test_find_thrash_collision_on_similar_task_and_artifacts():
    note_thrashing_worker(
        "conv-1",
        ThrashRecord(
            run_id="w1",
            task="修复 TopBar 缺少 named export",
            artifacts=("src/TopBar.tsx",),
            role="工程师",
        ),
    )
    cold = _plan(
        RunSpec(
            run_id="w2",
            role="修码员",
            task="修复 TopBar named export 缺失问题",
            deliverable=Deliverable(form="files", artifacts=["src/TopBar.tsx"]),
        )
    )
    hit = find_thrash_collision(cold, recent_thrash_records("conv-1"))
    assert hit is not None
    assert hit[1].run_id == "w1"
    assert "continue_from_run_id=`w1`" in thrash_reject_message(hit[1])


def test_continue_from_thrash_run_skips_collision():
    note_thrashing_worker(
        "conv-1",
        ThrashRecord(run_id="w1", task="修复导出错误", artifacts=("a.ts",), role="工程师"),
    )
    cont = _plan(
        RunSpec(
            run_id="w2",
            role="工程师",
            task="修复导出错误并验证",
            continue_from_run_id="w1",
            deliverable=Deliverable(form="files", artifacts=["a.ts"]),
        )
    )
    assert find_thrash_collision(cont, recent_thrash_records("conv-1")) is None


def test_unrelated_task_does_not_collide():
    note_thrashing_worker(
        "conv-1",
        ThrashRecord(run_id="w1", task="修复导出错误", artifacts=("a.ts",), role="工程师"),
    )
    other = _plan(
        RunSpec(
            run_id="w2",
            role="调研员",
            task="调研竞品定价策略并整理要点",
        )
    )
    assert find_thrash_collision(other, recent_thrash_records("conv-1")) is None


def test_post_worker_progress_thrash_fail_soft(monkeypatch):
    """thrash 记账炸了不得阻断 WORKER_COMPLETED 投递。"""
    from agentcore.runtime.coordination.host import post_worker_progress
    from agentcore.runtime.coordination.session import (
        CoordinationEventKind,
        CoordinationSession,
    )
    from agentcore.runtime.runs.types import RunPhase

    plan = _plan(
        RunSpec(
            run_id="w-thrash",
            role="工程师",
            task="修 TopBar",
            deliverable=Deliverable(form="files", artifacts=["src/TopBar.tsx"]),
        )
    )
    session = CoordinationSession(
        execution_id="e-thrash-soft",
        total_workers=1,
        conversation_id="conv-thrash-soft",
    )
    state = RunState(phase=RunPhase.COMPLETED, content="done")

    def _boom(*_a, **_k):
        raise RuntimeError("thrash accounting exploded")

    monkeypatch.setattr(
        "agentcore.runtime.coordination.thrash.thrash_record_from_node",
        _boom,
    )

    result = post_worker_progress(
        session,
        plan,
        {"w-thrash": state},
        sink=None,
        execution_id="e-thrash-soft",
        previously=set(),
    )
    assert "w-thrash" in result
    assert "w-thrash" in session.completed_run_ids
    events = session.drain_nowait()
    assert any(e.kind is CoordinationEventKind.WORKER_COMPLETED for e in events)
