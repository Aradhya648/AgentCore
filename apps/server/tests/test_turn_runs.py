"""执行与请求解耦 (C1 · slice 1a): TurnRunRegistry + EventSink.detach + SSE policy.

These lock the decoupling that keeps a long turn alive past a dropped connection
(实测案例复盘 案例 1: a 7-min turn lost its SSE and threw away the delivery):

- the registry tracks the detached run per conversation and stops it on demand,
- ``EventSink.detach`` caps the unread queue while still journaling for persistence,
- ``_event_generator`` detaches (run continues) vs cancels (handoff) on disconnect.

No DB, no HTTP — plain async tests (asyncio_mode=auto).
"""

import asyncio

import pytest

from agentcore.api import sse
from agentcore.runtime.events import (
    EventSink,
    EventType,
    FinishReason,
    content_delta,
    message_end,
    reasoning_delta,
    run_output_delta,
    run_plan,
    run_started,
    tool_progress,
    tool_use_end,
    tool_use_start,
)
from agentcore.runtime.turn_runs import TurnRunRegistry


def _plan():
    return run_plan(
        execution_id="exec-1",
        plan_type="multi_agent",
        task_summary="1 worker",
        agents=[{"id": "a1", "role": "研究员"}],
        runs=[{"id": "s1", "agent_id": "a1", "task": "调研", "depends_on": []}],
    )


async def _never() -> None:
    """A task body that never finishes on its own (stands in for a live turn)."""
    await asyncio.Event().wait()


# --- TurnRunRegistry -------------------------------------------------------


async def test_register_get_and_stop_cancels_then_discards():
    reg = TurnRunRegistry()
    task = asyncio.create_task(_never())
    run_id = reg.register(conversation_id="c1", task=task, sink=EventSink())

    run = reg.get("c1")
    assert run is not None and run.run_id == run_id

    # Stop signals the live task and reports it found one.
    assert reg.stop("c1") is True
    with pytest.raises(asyncio.CancelledError):
        await task

    # The done-callback clears the slot once the task settles; a second stop is a
    # no-op (idempotent) so a late 停止 click does not error.
    await asyncio.sleep(0)
    assert reg.get("c1") is None
    assert reg.stop("c1") is False


async def test_stop_unknown_conversation_is_false():
    reg = TurnRunRegistry()
    assert reg.stop("missing") is False


async def test_stop_all_and_drain_cancels_every_live_run():
    from agentcore.runtime.turn_runs import TurnRunRegistry

    reg = TurnRunRegistry()
    t1 = asyncio.create_task(_never())
    t2 = asyncio.create_task(_never())
    reg.register(conversation_id="c1", task=t1, sink=EventSink())
    reg.register(conversation_id="c2", task=t2, sink=EventSink())

    leftovers = await reg.stop_all_and_drain(timeout=2.0)
    assert leftovers == []
    with pytest.raises(asyncio.CancelledError):
        await t1
    with pytest.raises(asyncio.CancelledError):
        await t2
    await asyncio.sleep(0)
    assert reg.get("c1") is None
    assert reg.get("c2") is None


async def test_is_clean_cancel_true_under_shutdown_flag():
    from agentcore.runtime.turn_runs import TurnRunRegistry, turn_runs

    reg = TurnRunRegistry()
    turn_runs.end_shutdown_salvage()
    assert reg.is_clean_cancel("any") is False
    turn_runs.begin_shutdown_salvage()
    try:
        assert reg.is_clean_cancel("any") is True
        assert TurnRunRegistry.is_shutdown_salvage() is True
    finally:
        turn_runs.end_shutdown_salvage()


async def test_stop_and_drain_waits_for_unwind_before_returning():
    # Durable-resume preflight: unlike fire-and-forget ``stop``, ``stop_and_drain`` must not
    # return until the live run has actually unwound — the caller is about to take the same
    # ``workspace_lock`` the cancelled (suspended) run was holding. ``released`` stands in for
    # that lock being freed as the run's ``async with workspace_lock`` exits on CancelledError.
    reg = TurnRunRegistry()
    released = asyncio.Event()

    async def _parked_until_cancelled() -> None:
        try:
            await asyncio.Event().wait()  # parked on an interaction, like a suspended turn
        except asyncio.CancelledError:
            released.set()
            raise

    task = asyncio.create_task(_parked_until_cancelled())
    reg.register(conversation_id="c1", task=task, sink=EventSink())
    await asyncio.sleep(0)  # let the task actually start + park inside its try/except

    assert await reg.stop_and_drain("c1") is True
    # Genuinely drained (not merely signalled) by the time we return — this is the whole
    # point of the method, so the resume run never races the old run for the lock.
    assert task.done()
    assert released.is_set()

    await asyncio.sleep(0)  # let the done-callback clear the slot
    assert reg.get("c1") is None
    assert await reg.stop_and_drain("c1") is False  # idempotent


async def test_stop_and_drain_unknown_conversation_is_false():
    reg = TurnRunRegistry()
    assert await reg.stop_and_drain("missing") is False


async def test_drain_waits_without_cancelling():
    """Resume preflight: drain must not cancel a live (e.g. D9 new-turn) task."""
    reg = TurnRunRegistry()
    gate = asyncio.Event()

    async def _finishes_when_released() -> None:
        await gate.wait()

    task = asyncio.create_task(_finishes_when_released())
    reg.register(conversation_id="c1", task=task, sink=EventSink())
    await asyncio.sleep(0)

    # Still running within a short timeout → False (caller should 409).
    assert await reg.drain("c1", timeout=0.05) is False
    assert not task.done()
    assert not task.cancelled()

    gate.set()
    assert await reg.drain("c1", timeout=1.0) is True
    await asyncio.sleep(0)
    assert reg.get("c1") is None


async def test_drain_idle_conversation_is_true():
    reg = TurnRunRegistry()
    assert await reg.drain("missing") is True


async def test_stop_and_drain_frees_workspace_lock_for_resumer():
    # The exact deadlock this fixes: a suspended in-process run sits on its interaction holding
    # the folder ``workspace_lock``; durable ``/resume`` then takes that SAME lock. Without
    # draining first the resumer blocks until checkpoint_timeout (600s). ``stop_and_drain`` must
    # free it so the resume run acquires the lock immediately.
    from agentcore.workspace.locks import workspace_lock

    reg = TurnRunRegistry()
    key = "u1:f1:c1"
    holding = asyncio.Event()

    async def _suspended_run() -> None:
        async with workspace_lock(key):
            holding.set()
            await asyncio.Event().wait()  # parked on its interaction, still holding the lock

    task = asyncio.create_task(_suspended_run())
    reg.register(conversation_id="c1", task=task, sink=EventSink())
    await asyncio.wait_for(holding.wait(), timeout=1.0)  # the run now holds the lock

    await reg.stop_and_drain("c1")

    async def _resumer_takes_lock() -> bool:
        async with workspace_lock(key):
            return True

    # Drained ⇒ the lock is free, so the resumer acquires it within a tight bound; a regression
    # (drain that does not wait for the unwind, or no drain at all) would hang until the timeout.
    assert await asyncio.wait_for(_resumer_takes_lock(), timeout=1.0) is True


async def test_finished_run_is_discarded():
    reg = TurnRunRegistry()

    async def _quick() -> None:
        return None

    task = asyncio.create_task(_quick())
    reg.register(conversation_id="c1", task=task, sink=EventSink())
    await task
    await asyncio.sleep(0)  # let the done-callback run

    assert reg.get("c1") is None
    assert reg.stop("c1") is False


async def test_overlapping_run_cancels_old_and_stop_targets_new():
    """Regenerate race: overlap must cancel the prior task so /stop still works."""
    reg = TurnRunRegistry()
    first = asyncio.create_task(_never())
    second = asyncio.create_task(_never())
    try:
        reg.register(conversation_id="c1", task=first, sink=EventSink())
        reg.register(conversation_id="c1", task=second, sink=EventSink())
        assert reg.get("c1").task is second
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.sleep(0)
        # Older finish must NOT evict the newer registration.
        assert reg.get("c1") is not None
        assert reg.get("c1").task is second
        # Active (newer) run remains stoppable.
        assert reg.stop("c1") is True
        with pytest.raises(asyncio.CancelledError):
            await second
    finally:
        for t in (first, second):
            if not t.done():
                t.cancel()


async def test_overlap_cancel_marks_old_task_as_user_stop():
    """Superseded task must salvage as user-stop even after the slot is replaced."""
    reg = TurnRunRegistry()
    saw: dict[str, bool] = {}

    async def _old() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            saw["user_stop"] = reg.is_user_stop("c1")
            raise

    first = asyncio.create_task(_old())
    second = asyncio.create_task(_never())
    try:
        reg.register(conversation_id="c1", task=first, sink=EventSink())
        await asyncio.sleep(0)
        reg.register(conversation_id="c1", task=second, sink=EventSink())
        with pytest.raises(asyncio.CancelledError):
            await first
        assert saw.get("user_stop") is True
    finally:
        for t in (first, second):
            if not t.done():
                t.cancel()


# --- EventSink.detach ------------------------------------------------------


def test_detach_stops_queue_but_keeps_journal():
    sink = EventSink()
    sink.emit(_plan())  # journaled AND queued for SSE
    assert sink._queue.qsize() == 1

    sink.detach()
    sink.emit(run_started("s1", "a1"))  # after detach: journaled, NOT queued

    # The queue did not grow (the consumer is gone)...
    assert sink._queue.qsize() == 1
    # ...but the durable journal still captured the post-detach event, so the turn
    # persists + replays in full even though nobody was reading.
    journal = sink.execution_journal()
    assert [e["type"] for e in journal] == [
        EventType.RUN_PLAN.value,
        EventType.RUN_STARTED.value,
    ]


# --- _event_generator disconnect policy -----------------------------------


async def test_disconnect_detaches_run_when_detach_on_disconnect(monkeypatch):
    # detach_on_disconnect (chat turns): a client disconnect must NOT cancel the
    # detached run — it only detaches the sink so the run finishes + persists.
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    sink = EventSink()
    producer = asyncio.create_task(_never())
    try:
        gen = sse._event_generator(sink, producer, detach_on_disconnect=True)
        # Idle once so the generator is suspended INSIDE its try (at the heartbeat
        # yield); only then does aclose() raise GeneratorExit into the except.
        first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert first.startswith(":")

        await gen.aclose()  # simulate client disconnect

        assert sink._detached is True
        assert not producer.done()  # the run keeps going
    finally:
        producer.cancel()


async def test_disconnect_cancels_producer_by_default(monkeypatch):
    # Default policy (handoff SSEs): a disconnect cancels the producer so it stops
    # working for a response nobody will read.
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    sink = EventSink()
    producer = asyncio.create_task(_never())

    gen = sse._event_generator(sink, producer)
    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first.startswith(":")

    await gen.aclose()
    assert sink._detached is False
    with pytest.raises(asyncio.CancelledError):
        await producer


# --- EventSink reconnect history (slice 1b) --------------------------------


def test_history_coalesces_deltas_and_skips_liveliness():
    sink = EventSink()
    sink.emit(content_delta("a"))
    sink.emit(content_delta("b"))  # coalesces into the trailing content block
    sink.emit(tool_progress("delegate", 10))  # pure liveliness — skipped
    sink.emit(reasoning_delta("think"))
    sink.emit(tool_use_start("t1", "read", {}))
    sink.emit(tool_use_end("t1", "read", success=True, output="ok"))
    sink.emit(message_end(FinishReason.END_TURN))  # terminal — skipped

    hist = sink._history
    assert [e.type for e in hist] == [
        EventType.CONTENT_DELTA,
        EventType.REASONING_DELTA,
        EventType.TOOL_USE_START,
        EventType.TOOL_USE_END,
    ]
    assert hist[0].payload["delta"] == "ab"


def test_history_coalesces_run_deltas_per_run():
    sink = EventSink()
    sink.emit(run_output_delta("r1", "a1", "x"))
    sink.emit(run_output_delta("r1", "a1", "y"))  # same run → merge
    sink.emit(run_output_delta("r2", "a1", "z"))  # different run → new block

    hist = sink._history
    assert [(e.payload["run_id"], e.payload["delta"]) for e in hist] == [
        ("r1", "xy"),
        ("r2", "z"),
    ]


def test_history_caps_tool_result():
    sink = EventSink()
    big = "x" * 20_000
    sink.emit(tool_use_end("t1", "read_url", success=True, output=big))
    stored = sink._history[-1].payload["result"]
    assert stored.endswith("…")
    assert len(stored) < len(big)


async def test_take_over_replays_history_then_tails():
    sink = EventSink()
    sink.emit(content_delta("Hel"))
    sink.emit(content_delta("lo"))  # both queued AND folded into history
    sink.detach()  # consumer dropped — run continues
    sink.emit(content_delta("!"))  # history only (queue capped)

    snapshot = sink.take_over()
    # One coalesced content block carrying everything so far — the discarded queue
    # backlog is NOT replayed on top of it (no doubling).
    assert [e.type for e in snapshot] == [EventType.CONTENT_DELTA]
    assert snapshot[0].payload["delta"] == "Hello!"
    assert sink._queue.qsize() == 0

    # The queue is live again, so a post-attach event tails to the new consumer.
    sink.emit(content_delta(" more"))
    tail = await asyncio.wait_for(sink.get(), timeout=1.0)
    assert tail.payload["delta"] == " more"


async def test_take_over_on_finished_run_replays_then_ends():
    sink = EventSink()
    sink.emit(content_delta("done"))
    sink.close()  # run finished before the client re-attached

    snapshot = sink.take_over()
    assert [e.payload["delta"] for e in snapshot] == ["done"]
    # A closed sink hands the consumer the end sentinel so it replays then stops,
    # rather than re-opening a queue nothing will ever feed.
    assert await asyncio.wait_for(sink.get(), timeout=1.0) is None


async def test_take_over_synthesizes_message_end_after_detached_close():
    """No-cursor attach path: history skips MESSAGE_END — take_over must synthesize it
    so a client attaching in the detached persist window finalizes (align with cursor replay)."""
    sink = EventSink()
    sink.emit(content_delta("CEO 总结"))
    sink.detach()
    sink.emit(message_end(FinishReason.END_TURN, input_tokens=1, output_tokens=2))
    sink.close()

    snapshot = sink.take_over()
    assert [e.type for e in snapshot] == [EventType.CONTENT_DELTA, EventType.MESSAGE_END]
    assert snapshot[-1].payload == {"finish_reason": "end_turn"}
    assert await asyncio.wait_for(sink.get(), timeout=1.0) is None


async def test_attach_generator_no_cursor_replays_message_end(monkeypatch):
    """SSE attach without Last-Event-ID must surface the synthetic close frame."""
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    sink = EventSink()
    sink.emit(content_delta("Hi"))
    sink.detach()
    sink.emit(message_end(FinishReason.CANCELLED))
    sink.close()

    gen = sse._attach_generator(sink)
    frames: list[str] = []
    async for chunk in gen:
        frames.append(chunk)
        if "message_end" in chunk:
            break
    joined = "".join(frames)
    assert "message_end" in joined
    assert "cancelled" in joined


async def test_attach_generator_replays_then_tails_then_closes(monkeypatch):
    monkeypatch.setattr(sse, "_HEARTBEAT_INTERVAL_S", 0.01)
    sink = EventSink()
    sink.emit(content_delta("Hi"))
    sink.detach()  # the original consumer dropped

    gen = sse._attach_generator(sink)
    replayed = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert "content_delta" in replayed and "Hi" in replayed

    sink.emit(content_delta(" there"))  # live tail after re-attach
    tailed = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert " there" in tailed

    sink.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)
