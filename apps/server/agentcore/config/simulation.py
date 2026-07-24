"""AI Town simulation runtime tuning (M2+)."""

from pydantic import BaseModel, Field


class SimulationSettings(BaseModel):
    """Concurrency, cost, and demo knobs for simulation ticks.

    ``simulation_scripted`` (env ``SIMULATION_SCRIPTED``): when true, new runs
    prefer the deterministic schedule-based tick path (demo/dev). That path
    also emits a demo pulse (conversation/trade every 4 ticks, preset
    world_event every 8) so Unity demos stay observable without DeepSeek.
    Production default is false — LLM remains the primary path. Independently,
    ``advance_tick`` auto-falls back to scripted when DeepSeek cannot be
    resolved (warning log).

    Cost guards (demo-safe defaults; do not burn LLM by accident):
    - ``max_agents`` — persona roster slice at create/seed (env ``SIMULATION_MAX_AGENTS``)
    - ``max_ticks`` — refuse further advances once current_tick reaches the cap
      (env ``SIMULATION_MAX_TICKS``)
    """

    max_parallel_agents: int = Field(default=6, ge=1, le=32)
    agent_tick_timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0)
    simulation_scripted: bool = False
    # Conservative demo defaults — slice roster / stop runs before large LLM bills.
    max_agents: int = Field(default=5, ge=1, le=32)
    max_ticks: int = Field(default=48, ge=1, le=10_000)
