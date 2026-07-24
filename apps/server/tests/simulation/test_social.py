"""BE-14: relationship and mood update tests."""

from __future__ import annotations

from agentcore.simulation.agents.social import apply_social_updates, decay_mood
from agentcore.simulation.agents.tick_runner import AgentTickOutcome
from agentcore.simulation.scenarios.town.config import INITIAL_RELATIONSHIPS, seed_town_world
from agentcore.simulation.types import SimAgentAction


def test_seed_world_has_initial_relationships():
    world = seed_town_world()
    assert world.agents["zhao"].relationships["wang"] == INITIAL_RELATIONSHIPS["zhao"]["wang"]


def test_mood_decays_toward_neutral():
    assert decay_mood(0.5) == 0.45
    assert decay_mood(-0.3) == -0.25
    assert decay_mood(0.0) == 0.0


def test_speak_to_boosts_relation_and_mood():
    world = seed_town_world()
    world.tick = 1
    zhao_before = world.agents["zhao"].mood
    wang_rel_before = world.agents["zhao"].relationships["wang"]
    outcome = AgentTickOutcome(
        action=SimAgentAction(
            agent_id="zhao",
            action="speak_to",
            success=True,
            tool_args={"target_name": "王婶", "message": "早上好啊"},
        ),
        rounds=1,
        latency_ms=10,
        usage={},
        cost_usd=0.0,
    )
    apply_social_updates(world, [outcome])
    assert world.agents["zhao"].mood > zhao_before
    assert world.agents["zhao"].relationships["wang"] > wang_rel_before
