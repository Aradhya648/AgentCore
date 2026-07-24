"""Shared simulation wire types (Python ↔ contract-types)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentcore.simulation.observe.types import TickMetrics
from agentcore.simulation.vec3 import Vec3


class SimAgentState(BaseModel):
    """Per-agent snapshot on ``sim.agent_state`` and in tick snapshots."""

    agent_id: str
    name: str
    role: str
    location: str
    position: Vec3
    activity: str = ""
    mood: float = 0.0
    goal: str = ""
    last_thought: str = ""
    relationships: dict[str, float] = Field(default_factory=dict)
    tick_memories: list[str] = Field(default_factory=list)
    money: float = 100.0
    inventory: dict[str, int] = Field(default_factory=lambda: {"粮食": 3, "日用品": 2})


class SimAgentAction(BaseModel):
    """One agent decision within a tick (``sim.agent_action``)."""

    agent_id: str
    action: Literal[
        "move_to",
        "stay_here",
        "speak_to",
        "propose_trade",
        "propose_vote",
        "idle",
        "error",
    ]
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict | None = None
    success: bool = True
    detail: str = ""


class SimTickStartedPayload(BaseModel):
    run_id: str
    tick: int
    hour: int


class SimTickEndedPayload(BaseModel):
    run_id: str
    tick: int
    hour: int
    agent_count: int
    metrics: TickMetrics | None = None


class SimAgentStatePayload(BaseModel):
    run_id: str
    tick: int
    state: SimAgentState


class SimAgentActionPayload(BaseModel):
    run_id: str
    tick: int
    action: SimAgentAction


class WorldModifiersWire(BaseModel):
    """World-level knobs affected by scheduled events."""

    market_price_multiplier: float = 1.0
    storm_active: bool = False
    festival_active: bool = False
    square_attraction_boost: float = 0.0


class WorldEventWire(BaseModel):
    """One active world event in tick snapshots."""

    event_id: str
    kind: str
    event_type: str
    title: str
    description: str
    payload: dict = Field(default_factory=dict)
    tick_started: int
    duration_ticks: int = 1
    source: str = "scheduler"


class SimWorldEventPayload(BaseModel):
    """``sim.world_event`` SSE + sim_event row."""

    run_id: str
    tick: int
    event: WorldEventWire
    modifiers: WorldModifiersWire = Field(default_factory=WorldModifiersWire)


class TownGovernanceState(BaseModel):
    last_motion: str | None = None
    last_outcome: str | None = None
    yes_votes: int = 0
    no_votes: int = 0
    abstain_votes: int = 0
    policies: list[str] = Field(default_factory=list)


class SimTickSnapshot(BaseModel):
    """Persisted world frame for a single tick."""

    tick: int
    hour: int
    agents: dict[str, SimAgentState] = Field(default_factory=dict)
    event_log: list[str] = Field(default_factory=list)
    governance: TownGovernanceState = Field(default_factory=TownGovernanceState)
    active_events: list[WorldEventWire] = Field(default_factory=list)
    modifiers: WorldModifiersWire = Field(default_factory=WorldModifiersWire)
    metrics: TickMetrics | None = None
