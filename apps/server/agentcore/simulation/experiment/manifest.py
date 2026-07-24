"""Run manifest for reproducible simulation experiments (BE-27)."""

from __future__ import annotations

import subprocess
from datetime import datetime

from pydantic import BaseModel, Field

from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.llm import SimModelRoutingConfig
from agentcore.simulation.scenarios.town.config import TOWN_CONFIG, TOWN_PERSONAS

MANIFEST_VERSION = "1"
SIM_TICK_TEMPERATURE = 0.8


class RunManifest(BaseModel):
    """Frozen experiment descriptor stored on ``simulation_run.config``."""

    manifest_version: str = MANIFEST_VERSION
    scenario: str = "town"
    seed: int = 0
    personas: list[SimPersona] = Field(default_factory=lambda: list(TOWN_PERSONAS))
    regions: list[str] = Field(default_factory=lambda: list(TOWN_CONFIG.regions))
    model_routing: SimModelRoutingConfig | None = None
    temperature: float = SIM_TICK_TEMPERATURE
    # Demo/dev: force schedule-based ticks (no LLM). Also auto-enabled when
    # DeepSeek is missing at advance time — see SimulationService._resolve_scripted.
    scripted: bool = False
    created_at: datetime | None = None
    code_version: str | None = None


def resolve_code_version() -> str | None:
    """Best-effort git HEAD for cross-run comparison; optional."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return out.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _default_personas(scenario: str) -> tuple[SimPersona, ...]:
    if scenario == "show":
        from agentcore.simulation.scenarios.show.config import SHOW_PERSONAS

        return SHOW_PERSONAS
    return TOWN_PERSONAS


def _default_regions(scenario: str) -> tuple[str, ...]:
    if scenario == "show":
        from agentcore.simulation.scenarios.show.config import SHOW_CONFIG

        return SHOW_CONFIG.regions
    return TOWN_CONFIG.regions


def build_run_manifest(
    *,
    scenario: str,
    seed: int,
    model_routing: SimModelRoutingConfig | None = None,
    personas: tuple[SimPersona, ...] | None = None,
    regions: tuple[str, ...] | None = None,
    temperature: float = SIM_TICK_TEMPERATURE,
    scripted: bool = False,
    created_at: datetime | None = None,
    code_version: str | None = None,
) -> RunManifest:
    return RunManifest(
        scenario=scenario,
        seed=seed,
        personas=list(personas or _default_personas(scenario)),
        regions=list(regions or _default_regions(scenario)),
        model_routing=model_routing,
        temperature=temperature,
        scripted=scripted,
        created_at=created_at,
        code_version=code_version if code_version is not None else resolve_code_version(),
    )
