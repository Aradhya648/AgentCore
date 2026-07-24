"""Integration-style tests for replay_ticks (BE-28)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentcore.runtime.events import EventType
from agentcore.simulation.service import SimulationService


@pytest.mark.asyncio
async def test_replay_ticks_emits_persisted_events_and_tick_frame():
    repo = AsyncMock()
    repo.get_run = AsyncMock(
        return_value=SimpleNamespace(current_tick=2, status="running"),
    )
    repo.list_events_in_range = AsyncMock(
        return_value=[
            SimpleNamespace(
                tick_number=1,
                event_type="sim.agent_state",
                payload={
                    "run_id": "run-1",
                    "tick": 1,
                    "state": {"agent_id": "lin", "location": "市场"},
                },
            ),
        ],
    )
    snap = {"tick": 1, "hour": 9, "agents": {}, "event_log": []}
    repo.list_ticks_in_range = AsyncMock(
        return_value=[SimpleNamespace(tick_number=1, snapshot=snap)],
    )

    svc = SimulationService(repo)
    events = await svc.replay_ticks(
        "run-1",
        user_id="user-1",
        from_tick=1,
        to_tick=1,
    )

    assert len(events) == 2
    assert events[0].type == EventType.SIM_AGENT_STATE
    assert events[1].type == EventType.SIM_TICK_FRAME
    assert events[1].payload["tick_number"] == 1
    assert events[1].payload["snapshot"] == snap
