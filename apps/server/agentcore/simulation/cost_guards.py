"""Simulation cost / demo size guards (no LLM calls)."""

from __future__ import annotations

from collections.abc import Sequence

from agentcore.core.errors import ValidationError
from agentcore.simulation.agents.models import SimPersona


def slice_personas_for_run(
    personas: Sequence[SimPersona],
    *,
    max_agents: int,
) -> tuple[SimPersona, ...]:
    """Keep at most ``max_agents`` personas (stable order, create/seed path)."""
    if max_agents < 1:
        raise ValidationError("max_agents must be >= 1")
    roster = tuple(personas)
    if len(roster) <= max_agents:
        return roster
    return roster[:max_agents]


def ensure_under_max_ticks(current_tick: int, *, max_ticks: int) -> None:
    """Refuse advancing when ``current_tick`` already reached the configured cap.

    Called at the start of ``advance_tick``: if the run already has
    ``current_tick == max_ticks``, the next advance would exceed the budget.
    """
    if max_ticks < 1:
        raise ValidationError("max_ticks must be >= 1")
    if current_tick >= max_ticks:
        raise ValidationError(
            f"已达 max_ticks={max_ticks}，停止推进（当前 tick={current_tick}）"
        )
