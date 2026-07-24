"""EventSink persist-barrier combiner task lifecycle (no leaked pending tasks)."""

from __future__ import annotations

import asyncio

import pytest

from agentcore.runtime.events.sink import EventSink


@pytest.mark.asyncio
async def test_combine_persist_barriers_holds_task_ref_until_done():
    sink = EventSink()
    loop = asyncio.get_running_loop()
    f1: asyncio.Future[int | None] = loop.create_future()
    f2: asyncio.Future[int | None] = loop.create_future()

    combined = sink._combine_persist_barriers([f1, f2])
    assert combined is not None
    assert len(sink._barrier_tasks) == 1

    f1.set_result(1)
    f2.set_result(2)
    assert await combined == 2
    await asyncio.sleep(0)  # let done_callback discard
    assert sink._barrier_tasks == set()


@pytest.mark.asyncio
async def test_close_cancels_pending_barrier_tasks():
    sink = EventSink()
    loop = asyncio.get_running_loop()
    hang: asyncio.Future[int | None] = loop.create_future()
    ready: asyncio.Future[int | None] = loop.create_future()
    ready.set_result(0)

    combined = sink._combine_persist_barriers([ready, hang])
    assert combined is not None
    assert len(sink._barrier_tasks) == 1

    sink.close()
    assert sink._barrier_tasks == set()
    # Cancelling the waiter must not leave the combined future hanging forever
    # if the consumer never awaits it — close just drops the strong ref / cancels.
    await asyncio.sleep(0)
