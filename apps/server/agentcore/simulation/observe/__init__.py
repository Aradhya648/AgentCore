"""Observation and metrics (M4)."""

from agentcore.simulation.observe.types import TickMetrics

__all__ = ["MetricsAggregator", "TickMetrics"]


def __getattr__(name: str):
    if name == "MetricsAggregator":
        from agentcore.simulation.observe.metrics import MetricsAggregator

        return MetricsAggregator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
