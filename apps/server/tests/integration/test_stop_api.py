"""Integration tests for the explicit stop endpoint (执行与请求解耦 C1 · slice 1a).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Covers auth, ownership (IDOR), and the idempotent stop of a tracked run — the run
itself is a stand-in detached task registered directly in the ``TurnRunRegistry``
(the full SSE turn is exercised elsewhere), so this isolates the route + registry
contract: a live run is cancelled and reported, an absent one returns false.

Also pins the dual-cancel contract end-to-end: ``POST .../stop`` → registry cancel →
in-flight workers emit ``run_cancelled(reason=stop)`` with no hot/cold redirect follow-up.
"""

import asyncio
import contextlib

import httpx
import pytest

from agentcore.llm.provider.protocol import LLMChunk
from agentcore.runtime.events import EventSink, EventType, run_plan
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.wave import WaveScheduler
from agentcore.runtime.turn_runs import turn_runs
from tests.integration.conftest import register_and_login
from tests.runs_executor.conftest import _executor


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _never() -> None:
    await asyncio.Event().wait()


async def test_stop_requires_auth(client):
    cid = "00000000-0000-0000-0000-000000000000"
    assert (await client.post(f"/v1/conversations/{cid}/stop")).status_code == 401


async def test_stop_idempotent_and_cancels_tracked_run(client):
    await register_and_login(client, "stopuser")
    conv = await _new_conversation(client, "stoppable")

    # Nothing running yet → idempotent false (a late click settles cleanly).
    r = await client.post(f"/v1/conversations/{conv}/stop")
    assert r.status_code == 200, r.text
    assert r.json() == {"stopped": False}

    # Register a stand-in detached run, then hard-cancel (pins cancel path).
    task = asyncio.create_task(_never())
    turn_runs.register(conversation_id=conv, task=task, sink=EventSink())
    try:
        r = await client.post(f"/v1/conversations/{conv}/stop")
        assert r.status_code == 200, r.text
        assert r.json() == {"stopped": True}
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()

    # After it settled, the slot is cleared so a second stop is false again.
    await asyncio.sleep(0)
    r = await client.post(f"/v1/conversations/{conv}/stop")
    assert r.json() == {"stopped": False}


async def test_stop_rejects_non_owner(client, new_client):
    await register_and_login(client, "stopowner")
    conv = await _new_conversation(client, "mine")

    async with new_client() as other:
        await register_and_login(other, "stopintruder")
        # Not owned → 404 (mirrors the handoff IDOR contract).
        assert (await other.post(f"/v1/conversations/{conv}/stop")).status_code == 404


async def test_stop_route_cancels_inflight_workers_reason_stop_no_followup(client):
    """POST /stop → turn_runs cancel → in-flight workers emit run_cancelled(reason=stop);
    no hot ``_rev*`` / cold ``_redir`` follow-up (整轮 abort, not 立即改此人)."""

    class _HangProvider:
        async def stream(self, request):  # noqa: ANN001
            yield LLMChunk(delta_content="半成品")
            await asyncio.sleep(30)
            yield LLMChunk(delta_content="…")

    await register_and_login(client, "stopwave")
    conv = await _new_conversation(client, "stop-wave")

    plan, _ = build_run_plan(
        [
            {"role": "A", "task": "做A"},
            {"role": "B", "task": "做B"},
        ],
        id_prefix="t",
    )
    sink = EventSink()
    # Surface anchor so execution_journal() exposes the durable buffer (real turns
    # always emit run_plan before workers start).
    sink.emit(
        run_plan(
            execution_id="e",
            plan_type="multi_agent",
            task_summary="2 workers",
            agents=[
                {"id": "t_1", "role": "A"},
                {"id": "t_2", "role": "B"},
            ],
            runs=[
                {"id": "t_1", "agent_id": "t_1", "task": "做A", "depends_on": []},
                {"id": "t_2", "agent_id": "t_2", "task": "做B", "depends_on": []},
            ],
        )
    )
    wave_task = asyncio.create_task(
        WaveScheduler().run(plan, _executor(plan, _HangProvider(), sink))
    )
    turn_runs.register(conversation_id=conv, task=wave_task, sink=sink)
    try:
        for _ in range(200):
            started = [e for e in sink._history if e.type is EventType.RUN_STARTED]
            if len(started) >= 2:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("workers never started before stop")
        await asyncio.sleep(0.05)

        r = await client.post(f"/v1/conversations/{conv}/stop")
        assert r.status_code == 200, r.text
        assert r.json() == {"stopped": True}

        with contextlib.suppress(asyncio.CancelledError):
            await wave_task
        await asyncio.sleep(0)

        cancelled = [e for e in sink._history if e.type is EventType.RUN_CANCELLED]
        assert len(cancelled) == 2
        assert {e.payload.get("reason") for e in cancelled} == {"stop"}
        assert {e.payload.get("run_id") for e in cancelled} == {"t_1", "t_2"}

        journal = sink.execution_journal() or []
        journal_cancelled = [e for e in journal if e.get("type") == "run_cancelled"]
        assert len(journal_cancelled) == 2
        assert {e["payload"].get("reason") for e in journal_cancelled} == {"stop"}

        # Whole-turn stop must not mint redirect follow-ups.
        follow_up_ids = [
            str(e.payload.get("run_id") or "")
            for e in sink._history
            if e.type is EventType.RUN_STARTED
            and (
                str(e.payload.get("run_id") or "").endswith("_redir")
                or "_rev" in str(e.payload.get("run_id") or "")
            )
        ]
        assert follow_up_ids == []
        assert not any(
            e.payload.get("replaces_run_id")
            for e in sink._history
            if e.type is EventType.RUN_STARTED
        )
        assert turn_runs.get(conv) is None
    finally:
        if not wave_task.done():
            wave_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wave_task
