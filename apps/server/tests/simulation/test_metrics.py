"""Unit tests for M4 observation metrics (BE-25)."""

from __future__ import annotations

from agentcore.simulation.interaction.models import InteractionResult, InteractionStateChange
from agentcore.simulation.observe.metrics import MetricsAggregator
from agentcore.simulation.scenarios.town.config import seed_town_world
from agentcore.simulation.world.engine import WorldEngine


def test_metrics_aggregator_computes_macro_indicators():
    world = seed_town_world()
    world.agents["lin"].mood = 0.2
    world.agents["chen"].mood = -0.2
    world.agents["lin"].relationships["chen"] = 0.5
    world.agents["chen"].relationships["lin"] = 0.5
    world.agents["zhao"].relationships["wang"] = -0.4

    trade = InteractionResult(
        request_id="t1",
        kind="trade",
        status="completed",
        initiator_id="zhao",
        target_id="wang",
        summary="成交",
        state_changes=InteractionStateChange(
            money_transfers=[{"from": "zhao", "to": "wang", "amount": 12.5}]
        ),
    )

    metrics = MetricsAggregator().aggregate(world, tick_interactions=[trade])

    assert metrics.tick == 0
    assert metrics.trade_count == 1
    assert metrics.trade_total_amount == 12.5
    assert 0.0 <= metrics.positive_relation_ratio <= 1.0
    assert metrics.population_by_region[world.agents["lin"].location] >= 1
    assert sum(metrics.population_by_region.values()) == len(world.agents)


import pytest


@pytest.mark.asyncio
async def test_metrics_persisted_on_snapshot():
    world = seed_town_world()
    engine = WorldEngine(world=world)
    snap = await engine.advance()
    metrics = MetricsAggregator().aggregate(world)
    snap_with_metrics = snap.model_copy(update={"metrics": metrics})
    assert snap_with_metrics.metrics is not None
    assert snap_with_metrics.metrics.tick == snap.tick
