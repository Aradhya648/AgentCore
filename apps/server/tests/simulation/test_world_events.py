"""Tests for world event scheduler (BE-22)."""

from __future__ import annotations

import pytest

from agentcore.simulation.world.events import EventScheduler, build_preset_event
from agentcore.simulation.world.events.models import WorldEventKind
from agentcore.simulation.world.state import WorldAgent, WorldState


def _mini_world(*, square_count: int = 2) -> WorldState:
    world = WorldState()
    for i in range(max(square_count, 2)):
        aid = f"a{i}"
        loc = "广场" if i < square_count else "市场"
        world.agents[aid] = WorldAgent(agent_id=aid, name=aid, role="居民", location=loc)
    return world


def test_daily_market_open_at_hour_8():
    world = _mini_world()
    world.tick = 1
    world.hour = 8
    scheduler = EventScheduler(seed=42)
    events = scheduler.evaluate_tick_start(world)
    titles = [e.title for e in events]
    assert "市场开市" in titles
    assert any(e.kind == WorldEventKind.DAILY for e in events)


def test_preset_price_surge_sets_multiplier():
    world = _mini_world()
    world.tick = 3
    world.hour = 10
    scheduler = EventScheduler(seed=1)
    event = build_preset_event("price_surge", tick=3, payload={"multiplier": 2.0})
    scheduler.evaluate_tick_start(world, pending_injections=[event])
    assert world.modifiers.market_price_multiplier == pytest.approx(2.0)
    assert any(e.event_type == "price_surge" for e in world.active_events)


def test_emergent_crowding_when_square_packed():
    world = _mini_world(square_count=5)
    world.tick = 5
    world.hour = 15
    scheduler = EventScheduler(seed=0)
    events = scheduler.evaluate_tick_start(world)
    assert any(e.event_type == "crowding" for e in events)


def test_expire_stale_drops_old_events():
    world = _mini_world()
    event = build_preset_event("storm", tick=1)
    world.active_events = [event]
    world.modifiers.storm_active = True
    world.tick = event.tick_expires + 1
    scheduler = EventScheduler(seed=0)
    scheduler.expire_stale(world)
    assert world.active_events == []
    assert world.modifiers.storm_active is False
