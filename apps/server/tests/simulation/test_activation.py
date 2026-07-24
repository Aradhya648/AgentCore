"""BE-09: agent activation strategy tests."""

from __future__ import annotations

import pytest

from agentcore.simulation.agents.activation import (
    ActivateAllStrategy,
    ActivationContext,
    ScheduleAwareActivationStrategy,
    apply_schedule_fallback,
)
from agentcore.simulation.scenarios.town.config import TOWN_PERSONAS, seed_town_world


def test_activate_all_includes_everyone():
    world = seed_town_world()
    world.tick = 1
    ctx = ActivationContext(world=world, personas=TOWN_PERSONAS, tick=1, hour=9)
    decision = ActivateAllStrategy().select(ctx)
    assert len(decision.activated) == 10
    assert decision.skipped == ()


def test_schedule_aware_skips_sleeping_hours():
    world = seed_town_world()
    ctx = ActivationContext(world=world, personas=TOWN_PERSONAS, tick=1, hour=1)
    decision = ScheduleAwareActivationStrategy().select(ctx)
    assert len(decision.skipped) == 10
    assert decision.activated == ()


def test_schedule_aware_activates_daytime():
    world = seed_town_world()
    ctx = ActivationContext(world=world, personas=TOWN_PERSONAS, tick=1, hour=10)
    decision = ScheduleAwareActivationStrategy().select(ctx)
    assert len(decision.activated) == 10


@pytest.mark.asyncio
async def test_schedule_fallback_updates_agent():
    world = seed_town_world()
    world.tick = 1
    world.hour = 1
    persona = TOWN_PERSONAS[0]
    await apply_schedule_fallback(world, persona)
    agent = world.agents[persona.agent_id]
    assert "睡" in agent.activity or agent.location == "住宅区"
