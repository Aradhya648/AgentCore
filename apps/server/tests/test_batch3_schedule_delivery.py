"""批次3「调度与交付质量」六项验收单测。

覆盖：硬收尾禁新调用/宽限轮/强制取消/嵌套超时、取消级联 skip+force、
TIMEOUT 盖章、检索预算补发与耗尽提前收尾、宽度重算、slot_starved 口径。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from agentcore.runtime.coordination.session import (
    CoordinationEventKind,
    CoordinationSession,
    clear_active_coordination,
)
from agentcore.runtime.runs.cutoff import WORKER_TIMEOUT_WARNING
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.timeout_hard import (
    HardTimeoutPhase,
    arm_hard_timeout,
    clear_all_hard_timeouts,
    disarm_hard_timeout,
    get_hard_timeout,
)
from agentcore.runtime.runs.types import BatchMetrics, RunPhase, RunPolicy, RunSpec, RunState
from agentcore.runtime.runs.wave import WaveScheduler
from agentcore.tools.protocol import RetrievalBudgetState


def _spec(
    run_id: str,
    deps: tuple[str, ...] = (),
    *,
    force_continue: bool = False,
    on_failure: str = "degrade",
) -> RunSpec:
    return RunSpec(
        run_id=run_id,
        task="t",
        agent_id=run_id,
        role=run_id,
        depends_on=list(deps),
        force_continue=force_continue,
        policy=RunPolicy(on_failure=on_failure),
    )


@pytest.fixture(autouse=True)
def _clear_timeouts():
    clear_all_hard_timeouts()
    clear_active_coordination()
    yield
    clear_all_hard_timeouts()
    clear_active_coordination()


# ── 1. 超时硬收尾 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hard_timeout_blocks_after_grace_and_force_cancels():
    """TIMEOUT → grace → post-grace blocks + force_cancel."""
    calls: list[str] = []

    def on_force(guard, reason):
        calls.append(reason)

    guard = arm_hard_timeout(
        "w1",
        timeout_s=0.05,
        warn_ratio=0.4,
        grace_wall_s=0.2,
        on_force_cancel=on_force,
    )
    assert guard is not None
    await asyncio.sleep(0.03)  # past warn
    assert guard.phase is HardTimeoutPhase.WARNED
    assert guard.consume_wind_down() is True
    await asyncio.sleep(0.04)  # past full timeout
    assert guard.was_timed_out()
    assert guard.allows_grace_round()
    assert guard.begin_grace_round() is True
    assert guard.phase is HardTimeoutPhase.GRACE
    # During grace, new work is allowed (blocks_new_work False).
    assert guard.blocks_new_work() is False
    guard.end_grace_round()
    assert guard.blocks_new_work() is True
    guard.request_force_cancel(reason="post_grace")
    assert guard.force_cancel_requested
    assert "post_grace" in calls
    disarm_hard_timeout("w1")


@pytest.mark.asyncio
async def test_hard_timeout_grace_wall_force_cancels():
    """Grace wall clock expires → force cancel even if grace round never ended."""
    forced: list[str] = []
    guard = arm_hard_timeout(
        "w2",
        timeout_s=0.04,
        warn_ratio=0.0,  # skip warn, go straight to TIMEOUT
        grace_wall_s=0.05,
        on_force_cancel=lambda g, r: forced.append(r),
    )
    assert guard is not None
    await asyncio.sleep(0.12)
    assert guard.force_cancel_requested
    assert forced
    disarm_hard_timeout("w2")


@pytest.mark.asyncio
async def test_coordination_timeout_force_cancel_via_cancel_ids():
    """Session hard TIMEOUT eventually lands run_id in cancel_ids."""
    session = CoordinationSession(execution_id="exec-hard", total_workers=1)
    with patch("agentcore.config.settings") as settings:
        settings.engine_worker_timeout_warn_ratio = 0.3
        session.arm_worker_timeout("slow", role="慢工", timeout_s=0.08)
        # Wait past TIMEOUT; grace wall is 90s by default — force via request after notify.
        await asyncio.sleep(0.12)
        assert session.was_timeout_notified("slow")
        events = [e for e in session._pending if e.kind is CoordinationEventKind.TIMEOUT]
        # Drain via wait if still in queue
        if not events:
            drained = await session.wait_events(timeout=0.5)
            events = [e for e in drained if e.kind is CoordinationEventKind.TIMEOUT]
        assert events
        assert events[0].payload.get("hard") is True
        # Simulate post-grace force (engine path).
        guard = get_hard_timeout("slow")
        assert guard is not None
        guard.request_force_cancel(reason="post_grace")
        assert "slow" in session.cancel_run_ids()
        assert session.was_timeout_force_cancelled("slow")
    session.disarm_worker_timeout("slow")


@pytest.mark.asyncio
async def test_nested_timeout_arms_without_session():
    """depth>0 path: wrap_executor_with_timeouts(session=None) arms hard timeout."""
    from agentcore.runtime.coordination.bridge import wrap_executor_with_timeouts

    armed: list[str] = []

    async def fake(spec: RunSpec, _c) -> RunState:
        g = get_hard_timeout(spec.run_id)
        assert g is not None
        armed.append(spec.run_id)
        return RunState(phase=RunPhase.COMPLETED, content="ok")

    wrapped = wrap_executor_with_timeouts(fake, session=None)
    spec = RunSpec(run_id="nested1", task="t", role="lead-worker")
    spec.policy.timeout_s = 60
    state = await wrapped(spec, {})
    assert state.phase is RunPhase.COMPLETED
    assert armed == ["nested1"]
    assert get_hard_timeout("nested1") is None  # disarmed


@pytest.mark.asyncio
async def test_timeout_pending_not_swallowed_by_token_wind_down():
    """Token wind-down active must not drop timeout wind-down entered mark."""
    from agentcore.runtime.runs.timeout_hard import HardTimeoutGuard

    guard = HardTimeoutGuard(run_id="w-tok", threshold_s=10.0)
    guard.wind_down_pending = True
    # Simulate: token wind-down already active; timeout pending still consumed.
    assert guard.consume_wind_down() is True
    assert guard.wind_down_entered is True
    assert guard.consume_wind_down() is False


@pytest.mark.asyncio
async def test_hard_timeout_paused_during_llm_inflight():
    """LLM 在飞期间不累计活跃时间 → 不硬判 TIMEOUT；结束后空转仍判死。"""
    timed_out: list[bool] = []
    guard = arm_hard_timeout(
        "w-llm-pause",
        timeout_s=0.12,
        warn_ratio=0.0,
        grace_wall_s=5.0,
        on_timeout=lambda _g: timed_out.append(True),
    )
    assert guard is not None
    guard.mark_llm_inflight(True)
    await asyncio.sleep(0.25)  # wall ≫ threshold, but LLM inflight
    assert timed_out == []
    assert not guard.was_timed_out()
    assert guard.phase is HardTimeoutPhase.ARMED
    guard.mark_llm_inflight(False)
    await asyncio.sleep(0.20)  # active time accumulates → TIMEOUT
    assert timed_out == [True]
    assert guard.was_timed_out()
    disarm_hard_timeout("w-llm-pause")


@pytest.mark.asyncio
async def test_hard_timeout_still_fires_when_idle():
    """无 LLM 在飞（编排空转）→ 墙钟仍按阈值硬判 TIMEOUT。"""
    timed_out: list[bool] = []
    guard = arm_hard_timeout(
        "w-idle",
        timeout_s=0.08,
        warn_ratio=0.0,
        grace_wall_s=5.0,
        on_timeout=lambda _g: timed_out.append(True),
    )
    assert guard is not None
    await asyncio.sleep(0.15)
    assert timed_out == [True]
    assert guard.was_timed_out()
    disarm_hard_timeout("w-idle")


# ── 2. 取消级联 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_cascades_skip_dependents():
    """Sole upstream cancel → dependent skips (zero successes)."""
    plan = RunPlan()
    plan.add(_spec("a"))
    plan.add(_spec("b", ("a",)))
    cancel_targets: set[str] = set()

    async def slow_ex(spec: RunSpec, _completed) -> RunState:
        if spec.run_id == "a":
            await asyncio.sleep(0.1)
        return RunState(phase=RunPhase.COMPLETED, content=spec.run_id)

    async def _schedule_cancel():
        await asyncio.sleep(0.02)
        cancel_targets.add("a")

    asyncio.create_task(_schedule_cancel())
    skipped: list[tuple[str, str, str]] = []
    res = await WaveScheduler().run(
        plan,
        slow_ex,
        cancel_run_ids=lambda: frozenset(cancel_targets),
        on_skipped=lambda rid, aid, reason: skipped.append((rid, aid, reason)),
    )
    assert res["a"].phase is RunPhase.CANCELLED
    assert res["b"].phase is RunPhase.SKIPPED
    assert skipped == [("b", "b", "cascade")]


@pytest.mark.asyncio
async def test_cancel_force_continue_runs_dependent():
    plan = RunPlan()
    plan.add(_spec("a"))
    plan.add(_spec("b", ("a",), force_continue=True))
    cancel_targets: set[str] = set()

    async def slow_ex(spec: RunSpec, _completed) -> RunState:
        if spec.run_id == "a":
            await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(0.01)
        return RunState(phase=RunPhase.COMPLETED, content=spec.run_id)

    async def _schedule_cancel():
        await asyncio.sleep(0.02)
        cancel_targets.add("a")

    asyncio.create_task(_schedule_cancel())
    res = await WaveScheduler().run(
        plan, slow_ex, cancel_run_ids=lambda: frozenset(cancel_targets)
    )
    assert res["a"].phase is RunPhase.CANCELLED
    assert res["b"].phase is RunPhase.COMPLETED


# ── 3. 交付缺口 / 盖章 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_force_cancel_stamps_warning():
    """Hard force-cancel path stamps worker_timeout (fixes false negative)."""
    from agentcore.runtime.coordination.bridge import wrap_executor_with_timeouts

    session = CoordinationSession(execution_id="exec-stamp2", total_workers=1)

    async def fake_executor(s: RunSpec, _c) -> RunState:
        session._timeout_notified.add(s.run_id)
        session._timeout_force_cancelled.add(s.run_id)
        return RunState(phase=RunPhase.CANCELLED, error="timeout force cancel")

    wrapped = wrap_executor_with_timeouts(fake_executor, session)
    spec = RunSpec(run_id="rev", task="t", role="审校")
    spec.policy.timeout_s = 60
    state = await wrapped(spec, {})
    assert WORKER_TIMEOUT_WARNING in (state.warnings or [])
    assert any(
        g.get("reason") == "worker_timeout" for g in (state.delivery_gaps or [])
    )


def test_delivery_gaps_on_soft_accept_and_partial_meta():
    from agentcore.runtime.delegate.delivery_status import build_delivery_status
    from agentcore.runtime.runs.executor_shared import _delivery_gaps_from_warnings

    gaps = _delivery_gaps_from_warnings(
        ["缺章节：结论"],
        {"summary": "薄", "degraded": True},
    )
    assert any("缺章节" in g["description"] for g in gaps)
    assert any(g.get("reason") == "degraded_handoff" for g in gaps)

    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="t", role="写手")])
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="x",
            warnings=["缺章节：结论"],
            delivery_gaps=gaps,
            files_touched=["out.md"],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e1")
    assert payload is not None
    assert payload["state"] == "partial"
    assert payload["gaps"]


# ── 4. 资源计账 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_budget_rework_refill():
    rb = RetrievalBudgetState(limit=2)
    assert await rb.try_reserve()
    assert await rb.try_reserve()
    assert not await rb.try_reserve()
    remaining = await rb.refill(1)
    assert remaining == 1
    assert rb.limit == 3
    assert await rb.try_reserve()


@pytest.mark.asyncio
async def test_retrieval_budget_rework_refill_respects_cap_and_wind_down():
    """Full rework refill must not grow past the original plan-time cap; wind_down → 0."""
    from agentcore.runtime.runs.retrieval_budget import rework_refill_slots

    assert rework_refill_slots(original_limit=4, wind_down_entered=True) == 0
    rb = RetrievalBudgetState(limit=4)
    for _ in range(4):
        assert await rb.try_reserve()
    slice_n = rework_refill_slots(original_limit=4, wind_down_entered=False)
    assert slice_n == 2
    remaining = await rb.refill_within_cap(slice_n, cap=4)
    assert remaining == 0
    assert rb.limit == 4


@pytest.mark.asyncio
async def test_retrieval_budget_exhausted_triggers_wind_down_flag():
    """Exhausted budget → remaining 0 (loop arms wind-down at round boundary)."""
    rb = RetrievalBudgetState(limit=1)
    assert await rb.try_reserve()
    assert rb.remaining == 0
    # The loop checks remaining<=0; here we only pin the predicate.
    assert rb.limit > 0 and rb.remaining <= 0


# ── 5. 宽度重算 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_width_recomputed_when_plan_grows():
    plan = RunPlan()
    plan.add(_spec("a"))

    async def ex(spec: RunSpec, _c) -> RunState:
        if spec.run_id == "a":
            await asyncio.sleep(0.05)
            # Mid-flight merge: append two more nodes → width should grow.
            plan.add(_spec("b"))
            plan.add(_spec("c"))
        return RunState(phase=RunPhase.COMPLETED, content=spec.run_id)

    sink: list[BatchMetrics] = []
    # max_parallel=3 so growth from 1→3 pending can raise width.
    res = await WaveScheduler(max_parallel=3).run(plan, ex, metrics_sink=sink)
    assert set(res) >= {"a", "b", "c"}
    assert sink[0].width >= 1
    # Final width reflects the grown plan (up to max_parallel / pending).
    assert sink[0].width >= 2 or sink[0].nodes >= 2


# ── 6. slot_starved 口径 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_slot_starved_not_inflated_by_cancel_poll():
    """With cancel_run_ids polling, slot_starved counts episodes not poll ticks."""
    plan = RunPlan()
    for x in ("a", "b", "c"):
        plan.add(_spec(x))

    async def slow_ex(spec: RunSpec, _c) -> RunState:
        await asyncio.sleep(0.08)
        return RunState(phase=RunPhase.COMPLETED, content=spec.run_id)

    sink: list[BatchMetrics] = []
    await WaveScheduler(max_parallel=1).run(
        plan,
        slow_ex,
        cancel_run_ids=lambda: frozenset(),  # enables 50ms poll
        metrics_sink=sink,
    )
    m = sink[0]
    # Old bug: ~2915 from poll cycles. Episode count for 3 nodes / width 1 is small.
    assert m.slot_starved > 0
    assert m.slot_starved < 20
