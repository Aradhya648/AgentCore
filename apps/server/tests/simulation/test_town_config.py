"""BE-10: town scenario configuration tests."""

from __future__ import annotations

import pytest

from agentcore.simulation.scenarios.town.config import (
    HOURLY_SCHEDULE,
    TOWN_AGENT_IDS,
    TOWN_CONFIG,
    TOWN_PERSONAS,
    TOWN_REGION_POSITIONS,
    TOWN_REGIONS,
    schedule_for_hour,
    schedule_hint_for_persona,
    seed_town_world,
)
from agentcore.simulation.world.engine import WorldEngine
from agentcore.simulation.world.locations import REGION_POSITIONS


def test_town_has_ten_residents():
    assert len(TOWN_PERSONAS) == 10
    assert len(TOWN_AGENT_IDS) == 10
    assert len({p.agent_id for p in TOWN_PERSONAS}) == 10


def test_region_map_matches_m1_contract():
    assert len(TOWN_REGIONS) == 11
    assert TOWN_REGION_POSITIONS == REGION_POSITIONS
    for name in ("图书馆", "工坊", "码头", "心动营地"):
        assert name in TOWN_REGIONS


def test_hourly_schedule_covers_24_hours():
    assert len(HOURLY_SCHEDULE) == 24
    for hour in range(24):
        slot = schedule_for_hour(hour)
        assert slot.location in TOWN_REGIONS
        assert slot.activity


def test_role_schedule_override():
    slot = schedule_hint_for_persona(TOWN_PERSONAS[0], hour=7)
    assert slot.location == "面包店"
    assert "面" in slot.activity or "炉" in slot.activity


def test_new_district_peak_hours_have_multiple_residents():
    """图书馆 / 工坊 / 码头 peaks are multi-resident, not solo landmarks."""
    by_id = {p.agent_id: p for p in TOWN_PERSONAS}

    def at(hour: int, location: str) -> set[str]:
        return {
            agent_id
            for agent_id, persona in by_id.items()
            if schedule_hint_for_persona(persona, hour).location == location
        }

    library_peak = at(13, "图书馆")
    workshop_peak = at(14, "工坊")
    dock_peak = at(17, "码头")

    assert "zhang" in library_peak
    assert len(library_peak) >= 3
    assert "wu" in workshop_peak
    assert len(workshop_peak) >= 3
    assert len(dock_peak) >= 4


def test_seed_town_world_has_all_agents():
    world = seed_town_world()
    assert len(world.agents) == 10
    for persona in TOWN_PERSONAS:
        agent = world.agents[persona.agent_id]
        assert agent.name == persona.name
        assert agent.position == TOWN_REGION_POSITIONS[persona.location]


@pytest.mark.asyncio
async def test_world_engine_reads_schedule():
    world = seed_town_world()
    engine = WorldEngine(world=world)
    world.hour = 11
    slot = engine.schedule_slot()
    assert slot.location == schedule_for_hour(11).location


def test_town_config_bundle():
    assert TOWN_CONFIG.personas == TOWN_PERSONAS
    assert TOWN_CONFIG.regions == TOWN_REGIONS


def test_personas_are_differentiated():
    neutral = {
        "openness": 0.5,
        "conscientiousness": 0.5,
        "extraversion": 0.5,
        "agreeableness": 0.5,
        "neuroticism": 0.5,
    }
    # No resident is left on the neutral placeholder Big Five profile.
    assert all(p.big_five.model_dump() != neutral for p in TOWN_PERSONAS)
    # Extraversion genuinely spreads across residents (introverts vs extraverts).
    extraversions = {round(p.big_five.extraversion, 3) for p in TOWN_PERSONAS}
    assert len(extraversions) >= 4
    # Every resident carries a layered goal stack, not a single flat goal.
    assert all(len(p.goals_stack) >= 2 for p in TOWN_PERSONAS)
