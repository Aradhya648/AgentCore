"""Post-tick relationship and mood updates (BE-14)."""

from __future__ import annotations

from collections.abc import Sequence

from agentcore.simulation.agents.tick_runner import AgentTickOutcome
from agentcore.simulation.world.state import WorldAgent, WorldState

MOOD_MIN = -1.0
MOOD_MAX = 1.0
RELATION_MIN = -1.0
RELATION_MAX = 1.0

# Per-tick natural mood regression toward neutral.
MOOD_DECAY = 0.05
# Interaction deltas.
SPEAK_MOOD_DELTA = 0.08
SPEAK_RELATION_DELTA = 0.06
SUCCESS_MOOD_DELTA = 0.03
ERROR_MOOD_DELTA = -0.05
COLOCATE_RELATION_DELTA = 0.01


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def decay_mood(mood: float) -> float:
    """Regress mood toward neutral each tick."""
    if mood > 0:
        return clamp(mood - MOOD_DECAY, MOOD_MIN, MOOD_MAX)
    if mood < 0:
        return clamp(mood + MOOD_DECAY, MOOD_MIN, MOOD_MAX)
    return mood


def adjust_relation(agent: WorldAgent, other_id: str, delta: float) -> None:
    current = agent.relationships.get(other_id, 0.0)
    agent.relationships[other_id] = clamp(current + delta, RELATION_MIN, RELATION_MAX)


def apply_social_updates(
    world: WorldState,
    outcomes: Sequence[AgentTickOutcome],
) -> None:
    """Update mood decay and relationship weights from tick outcomes."""
    for agent in world.agents.values():
        agent.mood = decay_mood(agent.mood)

    for outcome in outcomes:
        action = outcome.action
        agent = world.agents.get(action.agent_id)
        if agent is None:
            continue
        if outcome.error is not None or not action.success:
            agent.mood = clamp(agent.mood + ERROR_MOOD_DELTA, MOOD_MIN, MOOD_MAX)
            continue
        if action.action == "speak_to" and action.tool_args:
            target_name = str(action.tool_args.get("target_name", "")).strip()
            target = _agent_by_name(world, target_name)
            if target is not None:
                agent.mood = clamp(agent.mood + SPEAK_MOOD_DELTA, MOOD_MIN, MOOD_MAX)
                target.mood = clamp(target.mood + SPEAK_MOOD_DELTA * 0.5, MOOD_MIN, MOOD_MAX)
                adjust_relation(agent, target.agent_id, SPEAK_RELATION_DELTA)
                adjust_relation(target, agent.agent_id, SPEAK_RELATION_DELTA * 0.5)
        elif action.success:
            agent.mood = clamp(agent.mood + SUCCESS_MOOD_DELTA, MOOD_MIN, MOOD_MAX)

    _apply_colocation_bonus(world)


def _agent_by_name(world: WorldState, name: str) -> WorldAgent | None:
    if not name:
        return None
    for agent in world.agents.values():
        if agent.name == name:
            return agent
    return None


def _apply_colocation_bonus(world: WorldState) -> None:
    """Tiny affinity bump for agents sharing a location without explicit interaction."""
    by_location: dict[str, list[WorldAgent]] = {}
    for agent in world.agents.values():
        by_location.setdefault(agent.location, []).append(agent)
    for group in by_location.values():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                adjust_relation(a, b.agent_id, COLOCATE_RELATION_DELTA)
                adjust_relation(b, a.agent_id, COLOCATE_RELATION_DELTA)
