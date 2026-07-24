"""AI Town simulation REST schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentcore.simulation.experiment.manifest import RunManifest
from agentcore.simulation.observe.types import TickMetrics
from agentcore.simulation.types import SimAgentAction, SimAgentState, SimTickSnapshot, Vec3


class InjectSimulationEventRequest(BaseModel):
    event_type: Literal["price_surge", "storm", "festival", "announcement", "custom"]
    payload: dict = Field(default_factory=dict)


class InjectSimulationEventResponse(BaseModel):
    run_id: str
    event_id: str
    event_type: str
    title: str
    queued_for_tick: int


class PatchSimulationAgentRequest(BaseModel):
    mood: float | None = None
    goal: str | None = None
    money: float | None = None


class PatchSimulationAgentResponse(BaseModel):
    run_id: str
    agent_id: str
    state: SimAgentState


class CreateSimulationRunRequest(BaseModel):
    scenario: str = "town"
    seed: int = 0
    # Demo/dev: schedule-based ticks without DeepSeek. Also set via
    # SIMULATION_SCRIPTED or manifest.scripted; missing DeepSeek auto-falls back.
    scripted: bool = False
    manifest: RunManifest | None = None


class SimulationRunSummary(BaseModel):
    id: str
    scenario: str
    seed: int
    status: str
    current_tick: int

    model_config = {"from_attributes": True}


class SimulationRunStatusResponse(BaseModel):
    run_id: str
    status: str
    current_tick: int


class AdvanceTickResponse(BaseModel):
    run_id: str
    snapshot: SimTickSnapshot


class SimTickFrameResponse(BaseModel):
    run_id: str
    tick_number: int
    snapshot: SimTickSnapshot


class SimulationRunMetricsResponse(BaseModel):
    run_id: str
    metrics: list[TickMetrics]


class SimulationRunManifestResponse(BaseModel):
    run_id: str
    manifest: RunManifest


class Vec3Wire(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class SimAgentStateWire(BaseModel):
    agent_id: str
    name: str
    role: str
    location: str
    position: Vec3Wire
    activity: str = ""
    mood: float = 0.0
    goal: str = ""
    last_thought: str = ""


# Re-export canonical types for OpenAPI (same shapes as contract-types).
__all__ = [
    "AdvanceTickResponse",
    "CreateSimulationRunRequest",
    "InjectSimulationEventRequest",
    "InjectSimulationEventResponse",
    "PatchSimulationAgentRequest",
    "PatchSimulationAgentResponse",
    "SimAgentStateWire",
    "SimTickFrameResponse",
    "SimulationRunManifestResponse",
    "SimulationRunMetricsResponse",
    "SimulationRunStatusResponse",
    "SimulationRunSummary",
    "Vec3Wire",
    "SimAgentAction",
    "SimAgentState",
    "SimTickSnapshot",
    "Vec3",
    "RunManifest",
    "TickMetrics",
]
