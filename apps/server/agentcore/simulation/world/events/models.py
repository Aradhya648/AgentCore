"""World event Pydantic models (BE-22)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentcore.core.types import new_id


class WorldEventKind(StrEnum):
    """How the event was scheduled."""

    DAILY = "daily"
    PERIODIC = "periodic"
    RANDOM = "random"
    USER_INJECT = "user_inject"
    EMERGENT = "emergent"


class PresetEventType(StrEnum):
    """Injectable preset templates (god mode)."""

    PRICE_SURGE = "price_surge"
    STORM = "storm"
    FESTIVAL = "festival"
    ANNOUNCEMENT = "announcement"
    CUSTOM = "custom"


InjectEventType = Literal[
    "price_surge", "storm", "festival", "announcement", "custom"
]


class WorldEvent(BaseModel):
    """One active or queued world event."""

    event_id: str = Field(default_factory=new_id)
    kind: WorldEventKind
    event_type: str
    title: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)
    tick_started: int
    duration_ticks: int = 1
    source: str = "scheduler"

    @property
    def tick_expires(self) -> int:
        return self.tick_started + max(1, self.duration_ticks) - 1

    def is_active_at(self, tick: int) -> bool:
        return self.tick_started <= tick <= self.tick_expires

    def perception_line(self) -> str:
        return f"【{self.title}】{self.description}"


class WorldModifiers(BaseModel):
    """Mutable world-level knobs affected by events."""

    market_price_multiplier: float = 1.0
    storm_active: bool = False
    festival_active: bool = False
    square_attraction_boost: float = 0.0
