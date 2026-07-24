"""Five-class world event scheduler (BE-22)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentcore.simulation.world.events.models import (
    WorldEvent,
    WorldEventKind,
    WorldModifiers,
)
from agentcore.simulation.world.events.templates import build_preset_event

if TYPE_CHECKING:
    from agentcore.simulation.interaction.bus import InteractionBus
    from agentcore.simulation.world.state import WorldState

# --- Built-in schedule definitions ---------------------------------------------------

DAILY_EVENTS: dict[int, tuple[str, str]] = {
    8: ("市场开市", "早市开张，商贩陆续到位，交易活跃。"),
    18: ("市场闭市", "市场收摊，交易窗口关闭，居民转向居家。"),
}

PERIODIC_WEATHER_INTERVAL = 6
RANDOM_MERCHANT_PROBABILITY = 0.08
EMERGENT_CROWD_THRESHOLD = 4
EMERGENT_CROWD_LOCATION = "广场"


@dataclass
class EventScheduler:
    """Evaluate and apply world events at tick boundaries."""

    seed: int = 0
    _rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def evaluate_tick_start(
        self,
        world: WorldState,
        *,
        pending_injections: list[WorldEvent] | None = None,
        interaction_bus: InteractionBus | None = None,
    ) -> list[WorldEvent]:
        """Check all schedulers and return newly triggered events this tick."""
        tick = world.tick
        hour = world.hour
        triggered: list[WorldEvent] = []

        triggered.extend(self._daily_events(tick, hour))
        triggered.extend(self._periodic_events(tick))
        triggered.extend(self._random_events(tick))
        triggered.extend(self._emergent_events(world, tick))

        for event in pending_injections or []:
            event.tick_started = tick
            triggered.append(event)

        for event in triggered:
            self._apply_effects(world, event, interaction_bus=interaction_bus)

        return triggered

    def expire_stale(self, world: WorldState) -> list[WorldEvent]:
        """Drop expired events and recompute modifiers."""
        tick = world.tick
        before = list(world.active_events)
        world.active_events = [e for e in world.active_events if e.is_active_at(tick)]
        self._recompute_modifiers(world)
        return before

    def apply_events(
        self,
        world: WorldState,
        events: list[WorldEvent],
        *,
        interaction_bus: InteractionBus | None = None,
    ) -> list[WorldEvent]:
        """Apply already-built events (e.g. scripted demo pulses) mid-tick."""
        for event in events:
            event.tick_started = world.tick
            self._apply_effects(world, event, interaction_bus=interaction_bus)
        return events

    def _daily_events(self, tick: int, hour: int) -> list[WorldEvent]:
        spec = DAILY_EVENTS.get(hour)
        if spec is None:
            return []
        title, description = spec
        return [
            WorldEvent(
                kind=WorldEventKind.DAILY,
                event_type=f"daily_{hour:02d}",
                title=title,
                description=description,
                tick_started=tick,
                duration_ticks=1,
            )
        ]

    def _periodic_events(self, tick: int) -> list[WorldEvent]:
        if tick <= 0 or tick % PERIODIC_WEATHER_INTERVAL != 0:
            return []
        weathers = [
            ("天气转晴", "阳光和煦，户外活动增加。"),
            ("阴天微风", "天色阴沉，居民行动节奏放缓。"),
            ("小雨淅沥", "细雨绵绵，市场人流略减。"),
        ]
        title, description = self._rng.choice(weathers)
        return [
            WorldEvent(
                kind=WorldEventKind.PERIODIC,
                event_type="weather_change",
                title=title,
                description=description,
                tick_started=tick,
                duration_ticks=2,
            )
        ]

    def _random_events(self, tick: int) -> list[WorldEvent]:
        if self._rng.random() > RANDOM_MERCHANT_PROBABILITY:
            return []
        return [
            WorldEvent(
                kind=WorldEventKind.RANDOM,
                event_type="wandering_merchant",
                title="流浪商人到访",
                description="一位外地商人路过市场，带来稀罕货品与新鲜传闻。",
                tick_started=tick,
                duration_ticks=1,
                payload={"location": "市场"},
            )
        ]

    def _emergent_events(self, world: WorldState, tick: int) -> list[WorldEvent]:
        count = len(world.agents_at(EMERGENT_CROWD_LOCATION))
        if count < EMERGENT_CROWD_THRESHOLD:
            return []
        return [
            WorldEvent(
                kind=WorldEventKind.EMERGENT,
                event_type="crowding",
                title=f"{EMERGENT_CROWD_LOCATION}拥挤",
                description=(
                    f"{EMERGENT_CROWD_LOCATION}人流密集（{count} 人），"
                    "交谈与摩擦增多，秩序压力上升。"
                ),
                tick_started=tick,
                duration_ticks=1,
                payload={"location": EMERGENT_CROWD_LOCATION, "count": count},
            )
        ]

    def _apply_effects(
        self,
        world: WorldState,
        event: WorldEvent,
        *,
        interaction_bus: InteractionBus | None = None,
    ) -> None:
        world.active_events.append(event)
        line = f"tick{world.tick} {event.title}：{event.description}"
        world.event_log.append(line)

        if event.event_type == "price_surge":
            mult = float(event.payload.get("multiplier", 1.5))
            world.modifiers.market_price_multiplier = max(
                world.modifiers.market_price_multiplier, mult
            )
        elif event.event_type == "storm":
            world.modifiers.storm_active = True
        elif event.event_type == "festival":
            world.modifiers.festival_active = True
            world.modifiers.square_attraction_boost = max(
                world.modifiers.square_attraction_boost, 0.5
            )
            for agent in world.agents.values():
                if agent.location == "广场":
                    agent.mood = min(1.0, agent.mood + 0.1)
        elif event.event_type == "announcement" and interaction_bus is not None:
            motion = str(event.payload.get("motion", "")).strip()
            if motion:
                mayor_id = _find_mayor_secretary(world)
                interaction_bus.enqueue_kind(
                    "vote",
                    initiator_id=mayor_id,
                    params={"motion": motion, "source": "announcement"},
                )

        self._recompute_modifiers(world)

    def _recompute_modifiers(self, world: WorldState) -> None:
        tick = world.tick
        active = [e for e in world.active_events if e.is_active_at(tick)]
        world.active_events = active
        mods = WorldModifiers()
        for event in active:
            if event.event_type == "price_surge":
                mods.market_price_multiplier = max(
                    mods.market_price_multiplier,
                    float(event.payload.get("multiplier", 1.5)),
                )
            elif event.event_type == "storm":
                mods.storm_active = True
            elif event.event_type == "festival":
                mods.festival_active = True
                mods.square_attraction_boost = max(mods.square_attraction_boost, 0.5)
        world.modifiers = mods


def _find_mayor_secretary(world: WorldState) -> str:
    for agent in world.agents.values():
        if agent.role == "镇长秘书":
            return agent.agent_id
    return next(iter(world.agents))


def parse_pending_injections(raw: list[dict[str, Any]] | None) -> list[WorldEvent]:
    """Deserialize queued injections from run config."""
    if not raw:
        return []
    events: list[WorldEvent] = []
    for item in raw:
        try:
            events.append(WorldEvent.model_validate(item))
        except Exception:
            event_type = str(item.get("event_type", "custom"))
            events.append(
                build_preset_event(
                    event_type,
                    tick=0,
                    payload=dict(item.get("payload") or {}),
                )
            )
    return events
