"""Simulation run SSE stream registry (one EventSink per active run)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agentcore.runtime.events import EventSink


@dataclass
class SimulationStreamRegistry:
    """In-process map of run_id → live EventSink for SSE observers."""

    _sinks: dict[str, EventSink] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_or_create(self, run_id: str) -> EventSink:
        async with self._lock:
            sink = self._sinks.get(run_id)
            if sink is None:
                sink = EventSink()
                self._sinks[run_id] = sink
            return sink

    async def get(self, run_id: str) -> EventSink | None:
        async with self._lock:
            return self._sinks.get(run_id)

    async def remove(self, run_id: str) -> None:
        async with self._lock:
            sink = self._sinks.pop(run_id, None)
            if sink is not None:
                sink.close()

    def get_sync(self, run_id: str) -> EventSink | None:
        return self._sinks.get(run_id)


default_sim_stream_registry = SimulationStreamRegistry()
