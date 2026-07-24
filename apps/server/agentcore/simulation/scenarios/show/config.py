"""恋综场景配置：卡司 + 地点集（小镇区域 + 心动营地）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.scenarios.show.cast import (
    INITIAL_AFFINITY,
    SHOW_AGENT_IDS,
    SHOW_PERSONAS,
)
from agentcore.simulation.vec3 import Vec3
from agentcore.simulation.world.locations import (
    LOCATION_NEIGHBORS,
    LOCATIONS,
    REGION_POSITIONS,
    position_for_location,
)
from agentcore.simulation.world.state import WorldAgent, WorldState

# Day dates use existing town regions; night/ceremony use 心动营地.
SHOW_DAY_REGIONS: tuple[str, ...] = (
    "市场",
    "码头",
    "图书馆",
    "公园",
    "广场",
    "餐厅",
)
SHOW_NIGHT_REGION = "心动营地"
SHOW_REGIONS: tuple[str, ...] = LOCATIONS


class ShowScenarioConfig(BaseModel):
    personas: tuple[SimPersona, ...] = Field(default=SHOW_PERSONAS)
    regions: tuple[str, ...] = Field(default=SHOW_REGIONS)
    day_regions: tuple[str, ...] = Field(default=SHOW_DAY_REGIONS)
    night_region: str = SHOW_NIGHT_REGION
    region_positions: dict[str, Vec3] = Field(default_factory=lambda: dict(REGION_POSITIONS))
    region_neighbors: dict[str, list[str]] = Field(
        default_factory=lambda: {k: list(v) for k, v in LOCATION_NEIGHBORS.items()}
    )
    season_title: str = "心动小镇"
    episode_count: int = 7
    ticks_per_episode: int = 120


SHOW_CONFIG = ShowScenarioConfig()


def seed_show_world(personas: tuple[SimPersona, ...] | None = None) -> WorldState:
    """Seed a closed cast (no town NPCs) on the shared region graph."""
    world = WorldState()
    for p in personas or SHOW_PERSONAS:
        world.agents[p.agent_id] = WorldAgent(
            agent_id=p.agent_id,
            name=p.name,
            role=p.role,
            location=p.location,
            position=position_for_location(p.location),
            goal=p.goal,
            activity="抵达心动营地",
            relationships=dict(INITIAL_AFFINITY.get(p.agent_id, {})),
        )
    return world


def persona_by_id(agent_id: str, personas: tuple[SimPersona, ...] | None = None) -> SimPersona:
    for p in personas or SHOW_PERSONAS:
        if p.agent_id == agent_id:
            return p
    raise KeyError(agent_id)


__all__ = [
    "SHOW_AGENT_IDS",
    "SHOW_CONFIG",
    "SHOW_DAY_REGIONS",
    "SHOW_NIGHT_REGION",
    "SHOW_PERSONAS",
    "SHOW_REGIONS",
    "ShowScenarioConfig",
    "persona_by_id",
    "seed_show_world",
]
