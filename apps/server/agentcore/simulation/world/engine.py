"""Discrete tick clock and world hooks (no agent logic)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agentcore.simulation.scenarios.town.config import ScheduleSlot, schedule_for_hour
from agentcore.simulation.types import SimTickSnapshot
from agentcore.simulation.world.state import WorldState

TickHook = Callable[[WorldState], Awaitable[None] | None]


@dataclass
class WorldEngine:
    """Discrete tick advance for a single simulation run."""

    world: WorldState
    seed: int = 0
    _before_tick: list[TickHook] = field(default_factory=list)
    _after_tick: list[TickHook] = field(default_factory=list)

    @property
    def tick(self) -> int:
        return self.world.tick

    @property
    def hour(self) -> int:
        return self.world.hour

    def schedule_slot(self) -> ScheduleSlot:
        """Default town schedule for the current clock hour."""
        return schedule_for_hour(self.hour)

    def on_before_tick(self, hook: TickHook) -> None:
        self._before_tick.append(hook)

    def on_after_tick(self, hook: TickHook) -> None:
        self._after_tick.append(hook)

    async def advance(self) -> SimTickSnapshot:
        """Advance the world clock by one tick and return the post-advance snapshot."""
        for hook in self._before_tick:
            result = hook(self.world)
            if result is not None:
                await result
        self.world.advance_clock()
        for hook in self._after_tick:
            result = hook(self.world)
            if result is not None:
                await result
        return self.world.snapshot()
