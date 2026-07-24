"""In-memory world state for a simulation run."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentcore.simulation.types import (
    SimAgentState,
    SimTickSnapshot,
    TownGovernanceState,
    Vec3,
    WorldEventWire,
    WorldModifiersWire,
)
from agentcore.simulation.world.events.models import WorldEvent, WorldModifiers
from agentcore.simulation.world.locations import LOCATION_NEIGHBORS, position_for_location

if TYPE_CHECKING:
    from agentcore.simulation.interaction.bus import InteractionBus


@dataclass
class WorldAgent:
    agent_id: str
    name: str
    role: str
    location: str = "广场"
    position: Vec3 = field(default_factory=Vec3)
    activity: str = "闲逛"
    mood: float = 0.0
    goal: str = ""
    last_thought: str = ""
    relationships: dict[str, float] = field(default_factory=dict)
    tick_memories: list[str] = field(default_factory=list)
    money: float = 100.0
    inventory: dict[str, int] = field(default_factory=lambda: {"粮食": 3, "日用品": 2})

    def to_state(self) -> SimAgentState:
        return SimAgentState(
            agent_id=self.agent_id,
            name=self.name,
            role=self.role,
            location=self.location,
            position=self.position,
            activity=self.activity,
            mood=self.mood,
            goal=self.goal,
            last_thought=self.last_thought,
            relationships=dict(self.relationships),
            tick_memories=list(self.tick_memories),
            money=self.money,
            inventory=dict(self.inventory),
        )

    @classmethod
    def from_state(cls, state: SimAgentState) -> WorldAgent:
        return cls(
            agent_id=state.agent_id,
            name=state.name,
            role=state.role,
            location=state.location,
            position=state.position,
            activity=state.activity,
            mood=state.mood,
            goal=state.goal,
            last_thought=state.last_thought,
            relationships=dict(state.relationships),
            tick_memories=list(state.tick_memories),
            money=state.money,
            inventory=dict(state.inventory),
        )


@dataclass
class TownGovernance:
    last_motion: str | None = None
    last_outcome: str | None = None
    yes_votes: int = 0
    no_votes: int = 0
    abstain_votes: int = 0
    policies: list[str] = field(default_factory=list)

    def to_state(self) -> TownGovernanceState:
        return TownGovernanceState(
            last_motion=self.last_motion,
            last_outcome=self.last_outcome,
            yes_votes=self.yes_votes,
            no_votes=self.no_votes,
            abstain_votes=self.abstain_votes,
            policies=list(self.policies),
        )

    @classmethod
    def from_state(cls, state: TownGovernanceState) -> TownGovernance:
        return cls(
            last_motion=state.last_motion,
            last_outcome=state.last_outcome,
            yes_votes=state.yes_votes,
            no_votes=state.no_votes,
            abstain_votes=state.abstain_votes,
            policies=list(state.policies),
        )


@dataclass
class WorldState:
    tick: int = 0
    hour: int = 8
    agents: dict[str, WorldAgent] = field(default_factory=dict)
    event_log: list[str] = field(default_factory=list)
    active_events: list[WorldEvent] = field(default_factory=list)
    modifiers: WorldModifiers = field(default_factory=WorldModifiers)
    governance: TownGovernance = field(default_factory=TownGovernance)
    # Scripted demo story pack (price_surge | festival | town_hall). Not part of REST create
    # schema — set in-memory / tests only. Default keeps 涨价风波 arc.
    demo_pack: str = "price_surge"
    _mutation_lock: asyncio.Lock | None = field(default=None, repr=False, compare=False)
    interaction_bus: InteractionBus | None = field(default=None, repr=False, compare=False)
    def mutation_lock(self) -> asyncio.Lock:
        if self._mutation_lock is None:
            self._mutation_lock = asyncio.Lock()
        return self._mutation_lock

    def advance_clock(self) -> None:
        self.tick += 1
        self.hour = (8 + self.tick) % 24

    def agents_at(self, location: str, *, exclude: str | None = None) -> list[WorldAgent]:
        return [
            a for a in self.agents.values() if a.location == location and a.agent_id != exclude
        ]

    def perceive(self, agent_id: str) -> str:
        agent = self.agents[agent_id]
        here = self.agents_at(agent.location, exclude=agent_id)
        nearby = LOCATION_NEIGHBORS.get(agent.location, [])
        others_summary = ", ".join(f"{a.name}({a.activity})" for a in here) if here else "无"
        recent = self.event_log[-5:] if self.event_log else ["（尚无公共事件）"]
        active_lines = [
            e.perception_line() for e in self.active_events if e.is_active_at(self.tick)
        ]
        active_block = ""
        if active_lines:
            active_block = f"\n活跃事件：{'；'.join(active_lines)}"
        if self.modifiers.storm_active:
            active_block += "\n⚠ 暴风雨中，居民普遍倾向回家避险。"
        if self.modifiers.festival_active:
            active_block += "\n🎉 广场正在举办节日庆典，气氛热烈。"
        if self.modifiers.market_price_multiplier > 1.01:
            active_block += (
                f"\n💰 市场物价约为平时的 {self.modifiers.market_price_multiplier:.1f} 倍。"
            )
        return (
            f"【小镇感知 · tick {self.tick} · {self.hour:02d}:00】\n"
            f"你在：{agent.location}\n"
            f"当前活动：{agent.activity}\n"
            f"心情：{agent.mood:+.1f}\n"
            f"个人目标：{agent.goal}\n"
            f"同处此地：{others_summary}\n"
            f"可前往：{', '.join(nearby)}\n"
            f"近期镇事：{'；'.join(recent)}{active_block}"
        )

    async def record(self, line: str) -> None:
        async with self.mutation_lock():
            self.event_log.append(line)

    async def set_location(self, agent_id: str, location: str) -> None:
        async with self.mutation_lock():
            agent = self.agents[agent_id]
            agent.location = location
            agent.position = position_for_location(location)

    async def update_agent_activity(self, agent_id: str, activity: str) -> None:
        async with self.mutation_lock():
            self.agents[agent_id].activity = activity

    def snapshot(self) -> SimTickSnapshot:
        return SimTickSnapshot(
            tick=self.tick,
            hour=self.hour,
            agents={aid: a.to_state() for aid, a in self.agents.items()},
            event_log=list(self.event_log),
            governance=self.governance.to_state(),
            active_events=[_event_to_wire(e) for e in self.active_events],
            modifiers=WorldModifiersWire(**self.modifiers.model_dump()),
        )

    def load_snapshot(self, snap: SimTickSnapshot) -> None:
        self.tick = snap.tick
        self.hour = snap.hour
        self.event_log = list(snap.event_log)
        self.agents = {aid: WorldAgent.from_state(st) for aid, st in snap.agents.items()}
        self.governance = TownGovernance.from_state(snap.governance)

        self.active_events = [_wire_to_event(w) for w in snap.active_events]
        self.modifiers = WorldModifiers(**snap.modifiers.model_dump())


def _event_to_wire(event: WorldEvent) -> WorldEventWire:
    return WorldEventWire(
        event_id=event.event_id,
        kind=event.kind.value,
        event_type=event.event_type,
        title=event.title,
        description=event.description,
        payload=dict(event.payload),
        tick_started=event.tick_started,
        duration_ticks=event.duration_ticks,
        source=event.source,
    )


def _wire_to_event(wire: WorldEventWire) -> WorldEvent:
    from agentcore.simulation.world.events.models import WorldEvent, WorldEventKind

    return WorldEvent(
        event_id=wire.event_id,
        kind=WorldEventKind(wire.kind),
        event_type=wire.event_type,
        title=wire.title,
        description=wire.description,
        payload=dict(wire.payload),
        tick_started=wire.tick_started,
        duration_ticks=wire.duration_ticks,
        source=wire.source,
    )
