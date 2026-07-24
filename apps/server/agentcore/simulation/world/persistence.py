"""Tick snapshot persistence helpers (BE-11)."""

from __future__ import annotations

from agentcore.db.repositories.simulation import SimulationRepository
from agentcore.simulation.observe.types import TickMetrics
from agentcore.simulation.types import SimTickSnapshot
from agentcore.simulation.world.state import WorldState


async def persist_tick(
    repo: SimulationRepository,
    run_id: str,
    world: WorldState,
    *,
    status: str = "running",
    metrics: TickMetrics | None = None,
) -> SimTickSnapshot:
    """Write world snapshot to ``sim_tick`` and batch-update ``sim_agent`` rows."""
    snapshot = world.snapshot()
    if metrics is not None:
        snapshot = snapshot.model_copy(update={"metrics": metrics})
    await repo.write_tick(run_id, snapshot)
    states = [agent.to_state() for agent in world.agents.values()]
    await repo.bulk_update_agent_states(run_id, states)
    await repo.update_run_status(run_id, status=status, current_tick=snapshot.tick)
    return snapshot
