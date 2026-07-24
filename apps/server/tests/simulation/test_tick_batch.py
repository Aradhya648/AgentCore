"""BE-08: batch tick concurrency tests."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.simulation.agents.tick_batch import TickBatchOptions, run_agent_ticks_batch
from agentcore.simulation.scenarios.town.config import TOWN_PERSONAS, seed_town_world


def _stay_provider(agent_id: str, *, delay: float = 0.0) -> ScriptedProvider:
    payload = json.dumps(
        {
            "action": "stay_here",
            "activity": f"mock-{agent_id}",
            "reason": "probe",
            "thought": f"ok-{agent_id}",
        },
        ensure_ascii=False,
    )
    return ScriptedProvider([[content_chunk(payload)]])


@pytest.mark.asyncio
async def test_batch_runs_all_agents_concurrently():
    world = seed_town_world()
    world.tick = 1
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def _slow_tick(**kwargs):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        from agentcore.simulation.agents.tick_runner import run_agent_tick

        return await run_agent_tick(**kwargs)

    with patch(
        "agentcore.simulation.agents.tick_batch.run_agent_tick",
        side_effect=_slow_tick,
    ):
        result = await run_agent_ticks_batch(
            world=world,
            personas=TOWN_PERSONAS,
            llm=_stay_provider("x"),
            run_id="batch-test",
            text_mode=True,
            options=TickBatchOptions(max_parallel=6, timeout_seconds=30.0),
        )

    assert len(result.outcomes) == len(TOWN_PERSONAS)
    assert result.succeeded == len(TOWN_PERSONAS)
    assert peak >= 2


@pytest.mark.asyncio
async def test_batch_isolates_timeout_and_error():
    world = seed_town_world()
    world.tick = 1
    personas = TOWN_PERSONAS[:3]

    async def _maybe_fail(**kwargs):
        persona = kwargs["persona"]
        if persona.agent_id == "lin":
            await asyncio.sleep(0.2)
            raise RuntimeError("boom")
        if persona.agent_id == "chen":
            await asyncio.sleep(0.2)
            from agentcore.simulation.agents.tick_runner import run_agent_tick

            return await run_agent_tick(**kwargs)
        await asyncio.sleep(0.01)
        from agentcore.simulation.agents.tick_runner import run_agent_tick

        return await run_agent_tick(**kwargs)

    with patch(
        "agentcore.simulation.agents.tick_batch.run_agent_tick",
        side_effect=_maybe_fail,
    ):
        result = await run_agent_ticks_batch(
            world=world,
            personas=personas,
            llm=_stay_provider("x"),
            run_id="batch-test",
            text_mode=True,
            options=TickBatchOptions(max_parallel=3, timeout_seconds=0.05),
        )

    by_id = {o.action.agent_id: o for o in result.outcomes}
    assert by_id["lin"].error is not None
    assert by_id["chen"].error is not None
    assert by_id["zhao"].error is None
    assert result.succeeded == 1
    assert result.failed == 2
