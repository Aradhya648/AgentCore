"""Tests for the offline memory consolidation scheduler (memory/consolidation.py).

Covers the in-process debounce + turn-cap trigger and clean shutdown. The DB-bound
runner / sweeper are exercised at the integration layer; here the runner is injected
so the scheduling logic is tested in isolation, with small idle windows.
"""

import asyncio

from agentcore.memory import consolidation
from agentcore.memory.consolidation import MemoryConsolidationScheduler


class _Recorder:
    """Async runner stub: records conversation ids and pulses an event per call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.pulsed = asyncio.Event()

    async def __call__(self, conversation_id: str) -> None:
        self.calls.append(conversation_id)
        self.pulsed.set()


async def test_schedule_fires_after_idle():
    runner = _Recorder()
    sched = MemoryConsolidationScheduler(idle_seconds=0.05, turn_cap=100, runner=runner)
    sched.schedule("c1")
    assert runner.calls == []  # still inside the idle window
    await asyncio.wait_for(runner.pulsed.wait(), 1)
    assert runner.calls == ["c1"]


async def test_burst_debounces_to_single_run():
    runner = _Recorder()
    sched = MemoryConsolidationScheduler(idle_seconds=0.2, turn_cap=100, runner=runner)
    # A burst of turns, each well within the idle window → the timer keeps resetting.
    for _ in range(5):
        sched.schedule("c1")
        await asyncio.sleep(0.02)
    assert runner.calls == []  # nothing fires mid-burst
    await asyncio.wait_for(runner.pulsed.wait(), 1)
    await asyncio.sleep(0.05)  # give any erroneous second fire a chance to show
    assert runner.calls == ["c1"]  # consolidated ONCE over the whole burst


async def test_turn_cap_fires_immediately_ignoring_idle():
    runner = _Recorder()
    # Long idle so only the turn cap can trigger a fire.
    sched = MemoryConsolidationScheduler(idle_seconds=100, turn_cap=3, runner=runner)
    sched.schedule("c1")
    sched.schedule("c1")
    assert runner.calls == []  # below the cap, waiting on the (long) debounce
    sched.schedule("c1")  # third armed turn hits the cap → fire now
    await asyncio.wait_for(runner.pulsed.wait(), 1)
    assert runner.calls == ["c1"]


async def test_turn_cap_resets_after_firing():
    runner = _Recorder()
    sched = MemoryConsolidationScheduler(idle_seconds=100, turn_cap=2, runner=runner)
    sched.schedule("c1")
    sched.schedule("c1")  # cap reached → fire #1
    await asyncio.wait_for(runner.pulsed.wait(), 1)
    runner.pulsed.clear()
    # The count reset, so one more turn does NOT immediately re-fire.
    sched.schedule("c1")
    await asyncio.sleep(0.02)
    assert runner.calls == ["c1"]  # still only the first fire


async def test_conversations_are_scheduled_independently():
    runner = _Recorder()
    sched = MemoryConsolidationScheduler(idle_seconds=0.05, turn_cap=100, runner=runner)
    sched.schedule("c1")
    sched.schedule("c2")
    await asyncio.sleep(0.2)
    assert sorted(runner.calls) == ["c1", "c2"]


async def test_shutdown_cancels_pending_timer():
    runner = _Recorder()
    sched = MemoryConsolidationScheduler(idle_seconds=0.1, turn_cap=100, runner=runner)
    sched.schedule("c1")
    await sched.shutdown()
    await asyncio.sleep(0.2)
    assert runner.calls == []  # the armed debounce was cancelled on shutdown


async def test_shutdown_awaits_inflight_run():
    started = asyncio.Event()
    done: list[str] = []

    async def slow_runner(conversation_id: str) -> None:
        started.set()
        await asyncio.sleep(0.05)
        done.append(conversation_id)

    sched = MemoryConsolidationScheduler(idle_seconds=100, turn_cap=1, runner=slow_runner)
    sched.schedule("c1")  # cap=1 → fires immediately
    await asyncio.wait_for(started.wait(), 1)  # the run is in flight
    await sched.shutdown()  # must await it to completion, not abandon it
    assert done == ["c1"]


async def test_runner_failure_is_swallowed():
    boom = asyncio.Event()

    async def boom_runner(conversation_id: str) -> None:
        boom.set()
        raise RuntimeError("consolidation blew up")

    sched = MemoryConsolidationScheduler(idle_seconds=0.02, turn_cap=100, runner=boom_runner)
    sched.schedule("c1")
    await asyncio.wait_for(boom.wait(), 1)
    # The background task raised; shutdown still drains cleanly without propagating.
    await sched.shutdown()


def test_schedule_consolidation_is_noop_when_disabled(monkeypatch):
    # The production entry point must do nothing (and not build the scheduler) when
    # the feature flag is off.
    monkeypatch.setattr(consolidation.settings, "memory_consolidation_enabled", False, raising=True)
    saved = consolidation._default_scheduler
    consolidation._default_scheduler = None
    try:
        consolidation.schedule_consolidation("c1")
        assert consolidation._default_scheduler is None
    finally:
        consolidation._default_scheduler = saved
