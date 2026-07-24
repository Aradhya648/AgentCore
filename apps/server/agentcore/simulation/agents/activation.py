"""Agent activation strategy — decide which agents run LLM inference each tick (BE-09)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.scenarios.town.schedule import schedule_hint_for_persona
from agentcore.simulation.world.state import WorldState

_SLEEP_KEYWORDS = frozenset({"睡觉", "入睡", "就寝", "安眠"})


@dataclass(frozen=True)
class ActivationContext:
    """Inputs available when choosing agents for the current tick."""

    world: WorldState
    personas: Sequence[SimPersona]
    tick: int
    hour: int


@dataclass(frozen=True)
class ActivationDecision:
    """Which personas participate in LLM inference this tick."""

    activated: tuple[SimPersona, ...]
    skipped: tuple[SimPersona, ...]
    reasons: dict[str, str]

    @property
    def activated_ids(self) -> frozenset[str]:
        return frozenset(p.agent_id for p in self.activated)

    @property
    def skipped_ids(self) -> frozenset[str]:
        return frozenset(p.agent_id for p in self.skipped)


class AgentActivationStrategy(Protocol):
    """Pluggable per-tick agent selection; swap implementations without touching the executor."""

    def select(self, ctx: ActivationContext) -> ActivationDecision: ...


@dataclass(frozen=True)
class ActivateAllStrategy:
    """M2 baseline — every resident runs full LLM inference."""

    def select(self, ctx: ActivationContext) -> ActivationDecision:
        personas = tuple(ctx.personas)
        return ActivationDecision(
            activated=personas,
            skipped=(),
            reasons={p.agent_id: "activate_all" for p in personas},
        )


@dataclass(frozen=True)
class ScheduleAwareActivationStrategy:
    """Skip agents whose schedule slot indicates sleep (simple M2 rule)."""

    def select(self, ctx: ActivationContext) -> ActivationDecision:
        activated: list[SimPersona] = []
        skipped: list[SimPersona] = []
        reasons: dict[str, str] = {}
        for persona in ctx.personas:
            slot = schedule_hint_for_persona(persona, ctx.hour)
            if _is_sleeping(slot.activity):
                skipped.append(persona)
                reasons[persona.agent_id] = f"sleeping:{slot.activity}"
            else:
                activated.append(persona)
                reasons[persona.agent_id] = "active"
        return ActivationDecision(
            activated=tuple(activated),
            skipped=tuple(skipped),
            reasons=reasons,
        )


def _is_sleeping(activity: str) -> bool:
    return any(kw in activity for kw in _SLEEP_KEYWORDS)


async def apply_schedule_fallback(world: WorldState, persona: SimPersona) -> None:
    """Rule-based tick for agents that skip LLM inference — follow schedule hint."""
    slot = schedule_hint_for_persona(persona, world.hour)
    agent = world.agents[persona.agent_id]
    if agent.location != slot.location:
        await world.set_location(persona.agent_id, slot.location)
    await world.update_agent_activity(persona.agent_id, slot.activity)
    await world.record(
        f"tick{world.tick} {agent.name} 按日程在{slot.location}{slot.activity}（未激活推理）"
    )


def default_activation_strategy() -> AgentActivationStrategy:
    """Town M2 default: schedule-aware pruning."""
    return ScheduleAwareActivationStrategy()
