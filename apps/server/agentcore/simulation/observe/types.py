"""Observation wire types (no world imports — avoids cycles)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TickMetrics(BaseModel):
    """Macro indicators for one simulation tick."""

    tick: int
    hour: int
    avg_mood: float = 0.0
    trade_count: int = 0
    trade_total_amount: float = 0.0
    positive_relation_ratio: float = 0.0
    population_by_region: dict[str, int] = Field(default_factory=dict)
