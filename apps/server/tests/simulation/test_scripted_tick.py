"""Scripted tick path — advance without DeepSeek / mock LLM."""

from __future__ import annotations

import pytest

from agentcore.config import settings
from agentcore.db.repositories.simulation import SimulationRepository
from agentcore.simulation.agents.scripted import (
    DEMO_PACK_FESTIVAL,
    DEMO_PACK_TOWN_HALL,
    SCRIPTED_DEMO_INTERVAL,
    SCRIPTED_WORLD_EVENT_INTERVAL,
    drain_scripted_pending,
    normalize_demo_pack,
    run_scripted_agent_tick,
    run_scripted_demo_pulse,
    run_scripted_ticks,
)
from agentcore.simulation.interaction.bus import InteractionBus
from agentcore.simulation.scenarios.town.config import (
    INITIAL_RELATIONSHIPS,
    LIN_PERSONA,
    TOWN_PERSONAS,
    seed_town_world,
)
from agentcore.simulation.scenarios.town.schedule import schedule_hint_for_persona
from agentcore.simulation.world.engine import WorldEngine
from agentcore.simulation.world.events import EventScheduler, build_preset_event
from tests.integration.conftest import register_and_login

pytest_plugins = ["tests.integration.conftest"]

TEST_PASSWORD = "password123"
TICK_COUNT = 5
DEMO_TICK_COUNT = SCRIPTED_WORLD_EVENT_INTERVAL  # enough for interaction + world_event
_INTERACTION_TYPES = frozenset({"conversation", "trade", "vote"})
_WORLD_EVENT_TYPE = "sim.world_event"
_STORY_MARKERS = (
    "涨价风波",
    "试探",
    "趁乱",
    "爆发",
    "避险",
    "调解",
    "表决",
    "收场",
    "和解",
    "巩固",
)
_ARC_PULSE_COUNT = 9  # thickened Zhao↔Wang↔Liu arc length


@pytest.mark.asyncio
async def test_scripted_agent_tick_follows_schedule():
    world = seed_town_world()
    engine = WorldEngine(world=world)
    await engine.advance()
    # Lin is story-adjacent baker with a role override at many hours; scripted
    # path keeps workplace landings and only flavors activity copy.
    slot = schedule_hint_for_persona(LIN_PERSONA, world.hour)
    outcome = await run_scripted_agent_tick(world=world, persona=LIN_PERSONA)
    assert outcome.error is None
    assert outcome.action.success
    assert world.agents["lin"].location == slot.location
    assert world.agents["lin"].activity
    assert world.agents["lin"].activity.startswith("前往") or len(
        world.agents["lin"].activity
    ) >= 2


@pytest.mark.asyncio
async def test_scripted_schedule_disperses_non_cast_deterministically():
    """Non-protagonists stagger public landings; same inputs → same slot."""
    from agentcore.simulation.agents.scripted import _scripted_schedule_slot
    from agentcore.simulation.scenarios.town.config import persona_by_id

    hour = 12  # town-wide 公园 · 午休散步 — no role override for chen/yang/sun
    chen = persona_by_id("chen")
    yang = persona_by_id("yang")
    sun = persona_by_id("sun")
    zhao = persona_by_id("zhao")

    base = schedule_hint_for_persona(chen, hour)
    assert base.location == "公园"

    s_chen = _scripted_schedule_slot(chen, hour)
    s_yang = _scripted_schedule_slot(yang, hour)
    s_sun = _scripted_schedule_slot(sun, hour)
    s_zhao = _scripted_schedule_slot(zhao, hour)

    # Story cast keeps canonical landing.
    assert s_zhao.location == base.location
    # Non-cast: not everyone clones the same activity string.
    activities = {s_chen.activity, s_yang.activity, s_sun.activity}
    assert len(activities) >= 2
    # Re-run is bit-identical (deterministic).
    assert _scripted_schedule_slot(chen, hour) == s_chen
    assert _scripted_schedule_slot(yang, hour) == s_yang
    # At least one non-cast lands off the pile-up default (dispersion).
    non_cast_locs = {s_chen.location, s_yang.location, s_sun.location}
    assert len(non_cast_locs) >= 2 or "公园" not in non_cast_locs


@pytest.mark.asyncio
async def test_scripted_demo_pulse_emits_interaction_and_world_event():
    """Every N ticks: conversation/trade/vote; every 2N: preset world_event."""
    world = seed_town_world()

    world.tick = SCRIPTED_DEMO_INTERVAL - 1
    interactions, events = await run_scripted_demo_pulse(world)
    assert interactions == []
    assert events == []

    world.tick = SCRIPTED_DEMO_INTERVAL
    interactions, events = await run_scripted_demo_pulse(world)
    assert len(interactions) == 1
    assert interactions[0].kind == "conversation"
    assert interactions[0].status == "completed"
    assert len(interactions[0].transcript) >= 3
    assert "涨价风波" in interactions[0].summary
    assert events == []

    world.tick = SCRIPTED_WORLD_EVENT_INTERVAL
    interactions, events = await run_scripted_demo_pulse(world)
    assert len(interactions) == 1
    assert interactions[0].kind == "trade"
    assert interactions[0].status == "completed"
    assert len(interactions[0].transcript) >= 2
    assert len(events) == 1
    assert events[0].source == "scripted_demo"
    assert events[0].event_type == "price_surge"
    assert "赵老板" in events[0].description or "王婶" in events[0].description


@pytest.mark.asyncio
async def test_scripted_demo_pulse_story_arc_relation_and_chain():
    """Thickened rivalry arc: Liu mediation, vote beat, relation swing, event chain."""
    world = seed_town_world()
    zhao_wang0 = INITIAL_RELATIONSHIPS["zhao"]["wang"]
    assert world.agents["zhao"].relationships["wang"] == zhao_wang0

    summaries: list[str] = []
    kinds: list[str] = []
    world_event_types: list[str] = []
    relation_after_quarrel: float | None = None
    relation_after_thaw: float | None = None
    saw_liu = False

    for pulse in range(1, _ARC_PULSE_COUNT + 1):
        world.tick = SCRIPTED_DEMO_INTERVAL * pulse
        interactions, events = await run_scripted_demo_pulse(world)
        assert len(interactions) == 1
        result = interactions[0]
        kinds.append(result.kind)
        summaries.append(result.summary)
        assert len(result.transcript) >= 2
        assert all(line.text.strip() for line in result.transcript)
        joined = " ".join(line.text for line in result.transcript)
        assert any(
            token in joined
            for token in ("赵老板", "王婶", "进货", "涨价", "市场", "节日", "刘警官", "限价", "夜市")
        )
        if any(line.speaker_id == "liu" or "刘警官" in line.speaker_name for line in result.transcript):
            saw_liu = True
        if "刘警官" in joined or "刘警官" in result.summary:
            saw_liu = True

        if events:
            world_event_types.append(events[0].event_type)

        if pulse == 3:
            relation_after_quarrel = world.agents["zhao"].relationships["wang"]
        if pulse == 8:
            relation_after_thaw = world.agents["zhao"].relationships["wang"]

    assert kinds[0] == "conversation"
    assert kinds[1] == "trade"
    assert kinds[2] == "conversation"
    assert "vote" in kinds
    assert kinds[5] == "vote"
    assert any(marker in " ".join(summaries) for marker in _STORY_MARKERS)
    assert "试探" in summaries[0]
    assert "爆发" in summaries[2]
    assert "表决" in summaries[5]
    assert "和解" in summaries[7]
    assert saw_liu

    assert relation_after_quarrel is not None
    assert relation_after_thaw is not None
    assert relation_after_quarrel < zhao_wang0
    assert relation_after_thaw > relation_after_quarrel

    assert world_event_types[:3] == ["price_surge", "storm", "festival"]


def test_normalize_demo_pack_defaults_to_price_surge():
    assert normalize_demo_pack(None) == "price_surge"
    assert normalize_demo_pack("") == "price_surge"
    assert normalize_demo_pack("Festival") == DEMO_PACK_FESTIVAL
    assert normalize_demo_pack("nope") == "price_surge"


@pytest.mark.asyncio
async def test_scripted_demo_pulse_gathers_in_new_districts():
    """Story beats with location=图书馆/工坊/码头 colocate rivals for Unity overlays."""
    world = seed_town_world()

    world.tick = SCRIPTED_DEMO_INTERVAL * 3  # 爆发 → 图书馆
    await run_scripted_demo_pulse(world)
    assert world.agents["zhao"].location == "图书馆"
    assert world.agents["wang"].location == "图书馆"

    world.tick = SCRIPTED_DEMO_INTERVAL * 4  # 避险 → 码头
    await run_scripted_demo_pulse(world)
    assert world.agents["zhao"].location == "码头"
    assert world.agents["wang"].location == "码头"

    world.demo_pack = DEMO_PACK_FESTIVAL
    world.tick = SCRIPTED_DEMO_INTERVAL * 4  # 互惠 → 工坊
    await run_scripted_demo_pulse(world)
    assert world.agents["zhao"].location == "工坊"
    assert world.agents["wang"].location == "工坊"

    world.demo_pack = DEMO_PACK_TOWN_HALL
    world.tick = SCRIPTED_DEMO_INTERVAL * 2  # 游说 → 图书馆
    await run_scripted_demo_pulse(world)
    assert world.agents["zhao"].location == "图书馆"
    assert world.agents["wang"].location == "图书馆"


@pytest.mark.asyncio
async def test_scripted_demo_pulse_festival_pack():
    """demo_pack=festival uses short festival arc (not price_surge copy)."""
    world = seed_town_world()
    world.demo_pack = DEMO_PACK_FESTIVAL
    world.tick = SCRIPTED_DEMO_INTERVAL
    interactions, events = await run_scripted_demo_pulse(world)
    assert len(interactions) == 1
    assert "节日庆典" in (interactions[0].summary or "")
    assert "涨价风波" not in (interactions[0].summary or "")

    world.tick = SCRIPTED_WORLD_EVENT_INTERVAL
    _ix, events = await run_scripted_demo_pulse(world)
    assert events and events[0].event_type == "festival"


@pytest.mark.asyncio
async def test_scripted_demo_pulse_town_hall_pack_has_vote():
    world = seed_town_world()
    world.demo_pack = DEMO_PACK_TOWN_HALL
    # Beat 4 @ tick 12 is the vote.
    world.tick = SCRIPTED_DEMO_INTERVAL * 4
    interactions, _events = await run_scripted_demo_pulse(world)
    assert len(interactions) == 1
    assert interactions[0].kind == "vote"
    assert "镇民大会" in (interactions[0].summary or "") or "表决" in (
        interactions[0].summary or ""
    )


@pytest.mark.asyncio
async def test_scripted_storm_inject_moves_agents_to_shelter():
    """God inject storm → same advance tick residents bias to shelter with readable thought."""
    world = seed_town_world()
    world.tick = 1
    world.hour = 10
    # Place rivals outdoors so shelter move is observable.
    await world.set_location("zhao", "市场")
    await world.set_location("wang", "市场")
    await world.set_location("lin", "公园")

    scheduler = EventScheduler(seed=1)
    storm = build_preset_event("storm", tick=1)
    scheduler.evaluate_tick_start(world, pending_injections=[storm])
    assert world.modifiers.storm_active

    personas = [p for p in TOWN_PERSONAS if p.agent_id in ("zhao", "wang", "lin")]
    outcomes = await run_scripted_ticks(world=world, personas=personas)
    assert len(outcomes) == 3
    for outcome in outcomes:
        assert outcome.action.tool_args.get("reason") == "storm_shelter"
        assert "避险" in (outcome.action.thought or "") or "暴风雨" in (outcome.action.thought or "")
    shelter = {"住宅区", "镇政厅", "面包店", "餐厅"}
    for agent_id in ("zhao", "wang", "lin"):
        loc = world.agents[agent_id].location
        assert loc in shelter, f"{agent_id} expected shelter, got {loc}"
        assert "避险" in world.agents[agent_id].activity or world.agents[
            agent_id
        ].activity.startswith("前往")


@pytest.mark.asyncio
async def test_scripted_festival_inject_gathers_public():
    world = seed_town_world()
    world.tick = 2
    world.hour = 14
    await world.set_location("zhao", "住宅区")
    await world.set_location("wang", "住宅区")

    scheduler = EventScheduler(seed=1)
    festival = build_preset_event("festival", tick=2)
    scheduler.evaluate_tick_start(world, pending_injections=[festival])
    assert world.modifiers.festival_active

    personas = [p for p in TOWN_PERSONAS if p.agent_id in ("zhao", "wang")]
    outcomes = await run_scripted_ticks(world=world, personas=personas)
    for outcome in outcomes:
        assert outcome.action.tool_args.get("reason") == "festival_gather"
        assert "节日" in (outcome.action.thought or "")
    assert world.agents["zhao"].location in {"广场", "市场", "公园", "图书馆", "工坊", "码头"}
    assert world.agents["wang"].location in {"广场", "市场", "公园", "图书馆", "工坊", "码头"}


@pytest.mark.asyncio
async def test_scripted_announcement_drains_vote():
    """Announcement inject enqueues vote; scripted drain completes it (not dropped)."""
    world = seed_town_world()
    world.tick = 4
    world.hour = 11
    bus = InteractionBus()
    world.interaction_bus = bus

    scheduler = EventScheduler(seed=1)
    announcement = build_preset_event(
        "announcement",
        tick=4,
        payload={"motion": "是否延长夜市开放时间？"},
    )
    scheduler.evaluate_tick_start(
        world, pending_injections=[announcement], interaction_bus=bus
    )
    assert bus.has_pending_kind("vote")

    # Agents react to pending vote by heading to town hall.
    personas = [p for p in TOWN_PERSONAS if p.agent_id in ("xu", "zhao", "wang", "liu")]
    await run_scripted_ticks(world=world, personas=personas)
    assert any(
        world.agents[aid].location == "镇政厅" for aid in ("xu", "zhao", "wang", "liu")
    )

    results = await drain_scripted_pending(world, bus)
    assert bus.pending_count == 0
    assert len(results) == 1
    assert results[0].kind == "vote"
    assert results[0].status == "completed"
    assert "夜市" in results[0].summary or "夜市" in (world.governance.last_motion or "")
    assert world.governance.last_outcome in {"通过", "否决", "平局"}


@pytest.mark.asyncio
async def test_scripted_demo_pulse_includes_vote_beat():
    world = seed_town_world()
    # Pulse 6 → vote beat in the thickened arc.
    world.tick = SCRIPTED_DEMO_INTERVAL * 6
    interactions, _events = await run_scripted_demo_pulse(world)
    assert len(interactions) == 1
    assert interactions[0].kind == "vote"
    assert interactions[0].status == "completed"
    assert interactions[0].state_changes.governance.get("motion")
    assert "表决" in interactions[0].summary or "投票" in interactions[0].summary


@pytest.mark.asyncio
async def test_scripted_advance_five_ticks_without_llm(client):
    """No mock LLM patch: missing DeepSeek + scripted opt-in still advances ticks."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    try:
        await register_and_login(client, "scripted-tick", password=TEST_PASSWORD)

        create_res = await client.post(
            "/v1/simulation/runs",
            json={"scenario": "town", "seed": 42, "scripted": True},
        )
        assert create_res.status_code == 201, create_res.text
        run_id = create_res.json()["id"]

        for expected in range(1, TICK_COUNT + 1):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
            assert tick_res.status_code == 200, tick_res.text
            snap = tick_res.json()["snapshot"]
            assert snap["tick"] == expected
            assert len(snap["agents"]) >= 1

        for tick_number in range(1, TICK_COUNT + 1):
            frame = await client.get(f"/v1/simulation/runs/{run_id}/ticks/{tick_number}")
            assert frame.status_code == 200, frame.text
            body = frame.json()
            assert body["tick_number"] == tick_number
            assert body["snapshot"]["tick"] == tick_number
    finally:
        settings.simulation_enabled = original


@pytest.mark.asyncio
async def test_scripted_demo_pulse_persists_observable_events(
    client, session_factory
):
    """Scripted multi-tick run leaves interaction and/or world_event in sim_event."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    try:
        await register_and_login(client, "scripted-demo", password=TEST_PASSWORD)

        create_res = await client.post(
            "/v1/simulation/runs",
            json={"scenario": "town", "seed": 42, "scripted": True},
        )
        assert create_res.status_code == 201, create_res.text
        run_id = create_res.json()["id"]

        for expected in range(1, DEMO_TICK_COUNT + 1):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
            assert tick_res.status_code == 200, tick_res.text
            assert tick_res.json()["snapshot"]["tick"] == expected

        async with session_factory() as session:
            repo = SimulationRepository(session)
            rows = await repo.list_events_in_range(run_id, 1, DEMO_TICK_COUNT)

        kinds = {row.event_type for row in rows}
        has_interaction = bool(kinds & _INTERACTION_TYPES)
        has_world_event = _WORLD_EVENT_TYPE in kinds
        assert has_interaction or has_world_event, (
            f"expected conversation/trade or sim.world_event after "
            f"{DEMO_TICK_COUNT} scripted ticks; got {sorted(kinds)}"
        )
        # Demo pulse should have produced both by SCRIPTED_WORLD_EVENT_INTERVAL.
        assert has_interaction, f"missing interaction rows; kinds={sorted(kinds)}"
        assert has_world_event, f"missing world_event rows; kinds={sorted(kinds)}"
    finally:
        settings.simulation_enabled = original


@pytest.mark.asyncio
async def test_advance_without_deepseek_auto_scripted(client, monkeypatch):
    """Without DeepSeek credentials, advance_tick falls back to scripted (no hard throw)."""
    from unittest.mock import AsyncMock

    from agentcore.simulation.llm import SimLlmNotConfigured

    original = settings.simulation_enabled
    settings.simulation_enabled = True
    monkeypatch.setattr(settings, "simulation_scripted", False)
    monkeypatch.setattr(
        "agentcore.simulation.service.build_sim_provider",
        AsyncMock(side_effect=SimLlmNotConfigured("no deepseek")),
    )

    try:
        await register_and_login(client, "auto-scripted", password=TEST_PASSWORD)

        create_res = await client.post(
            "/v1/simulation/runs",
            json={"scenario": "town", "seed": 7},
        )
        assert create_res.status_code == 201, create_res.text
        run_id = create_res.json()["id"]

        tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick_res.status_code == 200, tick_res.text
        assert tick_res.json()["snapshot"]["tick"] == 1

        frame = await client.get(f"/v1/simulation/runs/{run_id}/ticks/1")
        assert frame.status_code == 200
    finally:
        settings.simulation_enabled = original
