"""Per-tick macro metrics aggregation (BE-25)."""

from __future__ import annotations

from collections import Counter

from agentcore.simulation.interaction.models import InteractionResult
from agentcore.simulation.observe.types import TickMetrics
from agentcore.simulation.world.state import WorldState


class MetricsAggregator:
    """Compute lightweight tick-level metrics from world state and interactions."""

    def aggregate(
        self,
        world: WorldState,
        *,
        tick_interactions: list[InteractionResult] | None = None,
    ) -> TickMetrics:
        agents = list(world.agents.values())
        avg_mood = sum(a.mood for a in agents) / len(agents) if agents else 0.0

        trade_count = 0
        trade_total = 0.0
        for result in tick_interactions or []:
            if result.kind != "trade" or result.status != "completed":
                continue
            trade_count += 1
            for transfer in result.state_changes.money_transfers:
                trade_total += float(transfer.get("amount", 0.0))

        positive_edges = 0
        total_edges = 0
        for agent in agents:
            for weight in agent.relationships.values():
                total_edges += 1
                if weight > 0:
                    positive_edges += 1
        positive_ratio = positive_edges / total_edges if total_edges else 0.0

        population = Counter(agent.location for agent in agents)

        return TickMetrics(
            tick=world.tick,
            hour=world.hour,
            avg_mood=round(avg_mood, 4),
            trade_count=trade_count,
            trade_total_amount=round(trade_total, 2),
            positive_relation_ratio=round(positive_ratio, 4),
            population_by_region=dict(sorted(population.items())),
        )
