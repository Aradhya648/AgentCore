"""INT-03: M3 interaction protocol end-to-end integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.config import settings
from agentcore.db.repositories.simulation import SimulationRepository
from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.llm.resolve import ModelConfig
from agentcore.runtime.events import EventType
from agentcore.simulation.agents import tick_runner
from agentcore.simulation.agents.activation import ActivationDecision, AgentActivationStrategy
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.service import SimulationService
from agentcore.simulation.stream_registry import default_sim_stream_registry
from tests.integration.conftest import register_and_login

pytest_plugins = ["tests.integration.conftest"]

TEST_PASSWORD = "password123"
_MOCK_CFG = ModelConfig(
    model="mock",
    base_url="http://mock",
    api_key="x",
    source="platform",
    purpose="sim.town",
)


@dataclass(frozen=True)
class ActivateOnlyStrategy:
    """Run LLM inference for a fixed subset of residents."""

    agent_ids: frozenset[str]

    def select(self, ctx) -> ActivationDecision:  # noqa: ANN001
        activated = tuple(p for p in ctx.personas if p.agent_id in self.agent_ids)
        skipped = tuple(p for p in ctx.personas if p.agent_id not in self.agent_ids)
        reasons = {
            p.agent_id: ("active" if p.agent_id in self.agent_ids else "skipped")
            for p in ctx.personas
        }
        return ActivationDecision(activated=activated, skipped=skipped, reasons=reasons)


def _action_provider(*actions: dict) -> ScriptedProvider:
    return ScriptedProvider(
        [[content_chunk(json.dumps(action, ensure_ascii=False))] for action in actions]
    )


def _json_chunks(*payloads: dict | str) -> ScriptedProvider:
    rounds: list[list] = []
    for payload in payloads:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        rounds.append([content_chunk(text)])
    return ScriptedProvider(rounds)


def _service_factory(strategy: AgentActivationStrategy):
    def _factory(repo: SimulationRepository) -> SimulationService:
        return SimulationService(
            repo,
            stream_registry=default_sim_stream_registry,
            activation_strategy=strategy,
        )

    return _factory


async def _create_authed_run(client, *, username: str) -> str:
    await register_and_login(client, username, password=TEST_PASSWORD)
    create_res = await client.post("/v1/simulation/runs", json={"scenario": "town", "seed": 7})
    assert create_res.status_code == 201, create_res.text
    return create_res.json()["id"]


async def _noop_schedule_fallback(world, persona: SimPersona) -> None:  # noqa: ARG001
    """Keep colocated agents in place when only a subset is activated."""
    return


async def _advance_tick(client, run_id: str, provider: ScriptedProvider, *, strategy):
    with (
        patch.object(settings, "max_parallel_agents", 1),
        patch(
            "agentcore.simulation.service.apply_schedule_fallback",
            new=_noop_schedule_fallback,
        ),
        patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(provider, _MOCK_CFG)),
        ),
        patch(
            "agentcore.api.routes.simulation.runs._service",
            side_effect=_service_factory(strategy),
        ),
    ):
        tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
    assert tick_res.status_code == 200, tick_res.text
    return tick_res.json()["snapshot"]


async def _events_for_tick(session_factory, run_id: str, tick_number: int):
    async with session_factory() as session:
        repo = SimulationRepository(session)
        return await repo.list_events_for_tick(run_id, tick_number)


def _interaction_sse_events(run_id: str):
    sink = default_sim_stream_registry.get_sync(run_id)
    assert sink is not None
    return [event for event in sink.take_over() if event.type == EventType.SIM_INTERACTION]


@pytest.fixture(autouse=True)
def _force_llm_tick_mode(monkeypatch):
    """Pin ``simulation_scripted=False`` so a local ``.env`` (``SIMULATION_SCRIPTED=true``,
    a legitimate config) can't force scripted ticks that silently ignore the injected
    mock provider — the exact seam these INT-03 tests guard. (Open registration is
    handled globally by ``tests/integration/conftest.py::_open_registration``.)"""
    monkeypatch.setattr(settings, "simulation_scripted", False)


@pytest.mark.asyncio
async def test_conversation_path_speak_to(client, session_factory):
    """speak_to → InteractionBus conversation → sim_event + relations + SSE."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    try:
        run_id = await _create_authed_run(client, username="int03-conv")
        speak = {
            "action": "speak_to",
            "target_name": "王婶",
            "message": "今天菜价怎样？",
            "reason": "打听行情",
            "thought": "得问问王婶。",
        }
        provider = _json_chunks(
            speak,
            {"accept": True, "reason": "可以聊"},
            "好啊，赵老板。",
            "青菜两块八。",
            "行，我看看。",
        )
        strategy = ActivateOnlyStrategy(frozenset({"zhao"}))
        snapshot = await _advance_tick(client, run_id, provider, strategy=strategy)

        tick_number = snapshot["tick"]
        zhao = snapshot["agents"]["zhao"]
        assert zhao["location"] == "市场"
        assert zhao["relationships"]["wang"] > -0.4

        db_events = await _events_for_tick(session_factory, run_id, tick_number)
        conv_rows = [row for row in db_events if row.event_type == "conversation"]
        assert conv_rows, "expected conversation row in sim_event"
        interaction = conv_rows[0].payload["interaction"]
        assert interaction["kind"] == "conversation"
        assert interaction["status"] in ("completed", "rejected")

        sse_events = _interaction_sse_events(run_id)
        assert sse_events, "expected sim.interaction SSE"
        assert sse_events[0].payload["interaction"]["kind"] == "conversation"
    finally:
        settings.simulation_enabled = original


@pytest.mark.asyncio
async def test_trade_path_propose_trade(client, session_factory):
    """propose_trade → trade execution → sim_event + balances + SSE."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    try:
        run_id = await _create_authed_run(client, username="int03-trade")
        trade = {
            "action": "propose_trade",
            "target_name": "王婶",
            "item": "日用品",
            "quantity": 1,
            "price": 10.0,
            "reason": "补货",
            "thought": "买点日用品。",
        }
        # Tool + collect_from_outcomes may enqueue twice; script two accept rounds.
        provider = _json_chunks(
            trade,
            {"accept": True, "reason": "卖给你"},
            {"accept": False, "reason": "库存不足"},
        )
        strategy = ActivateOnlyStrategy(frozenset({"zhao"}))
        snapshot = await _advance_tick(client, run_id, provider, strategy=strategy)

        tick_number = snapshot["tick"]
        zhao = snapshot["agents"]["zhao"]
        wang = snapshot["agents"]["wang"]
        assert zhao["location"] == "市场" and wang["location"] == "市场"

        db_events = await _events_for_tick(session_factory, run_id, tick_number)
        trade_rows = [row for row in db_events if row.event_type == "trade"]
        assert trade_rows, "expected trade row in sim_event"
        statuses = {row.payload["interaction"]["status"] for row in trade_rows}
        assert statuses & {"completed", "rejected", "failed"}

        if any(row.payload["interaction"]["status"] == "completed" for row in trade_rows):
            assert zhao["money"] < 100.0
            assert wang["inventory"].get("日用品", 0) < 2
        else:
            assert statuses <= {"rejected", "failed"}

        sse_events = _interaction_sse_events(run_id)
        assert sse_events
        assert all(event.payload["interaction"]["kind"] == "trade" for event in sse_events)
    finally:
        settings.simulation_enabled = original


@pytest.mark.asyncio
async def test_vote_path_propose_vote(client, session_factory):
    """propose_vote → ballot collection → sim_event + governance + SSE."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    try:
        run_id = await _create_authed_run(client, username="int03-vote")
        motion = "是否同意本周市场休市一天？"
        # run_vote tallies EVERY agent standing in 镇政厅 (needs ≥2), and yes/no/abstain
        # each need a distinct body. Gather 3 residents that survive the max_agents=5
        # slice (chen/zhao/wang) into the hall. The old test drove 徐(xu) — persona #10,
        # sliced away — so nobody ever proposed, and only chen would have been present
        # anyway (DRIFT on both roster size and quorum).
        to_hall = {
            "action": "move_to",
            "destination": "镇政厅",
            "reason": "参会",
            "thought": "去开会。",
        }
        await _advance_tick(
            client,
            run_id,
            _json_chunks(to_hall, to_hall, to_hall),
            strategy=ActivateOnlyStrategy(frozenset({"chen", "zhao", "wang"})),
        )
        vote = {
            "action": "propose_vote",
            "motion": motion,
            "reason": "征求意见",
            "thought": "发起投票。",
        }
        # chen proposes (1 decision), then chen/zhao/wang each cast a ballot (3) — the
        # provider serves exactly these 4 chunks in order.
        provider = _json_chunks(
            vote,
            {"vote": "yes", "reason": "支持"},
            {"vote": "no", "reason": "反对"},
            {"vote": "abstain", "reason": "再想想"},
        )
        strategy = ActivateOnlyStrategy(frozenset({"chen"}))
        snapshot = await _advance_tick(client, run_id, provider, strategy=strategy)

        tick_number = snapshot["tick"]
        governance = snapshot["governance"]
        assert governance["last_motion"] == motion
        assert governance["yes_votes"] >= 1
        assert governance["no_votes"] >= 1
        assert governance["abstain_votes"] >= 1

        db_events = await _events_for_tick(session_factory, run_id, tick_number)
        vote_rows = [row for row in db_events if row.event_type == "vote"]
        assert vote_rows, "expected vote row in sim_event"
        gov = vote_rows[0].payload["interaction"].get("state_changes", {}).get("governance", {})
        assert gov.get("yes", 0) >= 1
        assert gov.get("no", 0) >= 1
        assert gov.get("abstain", 0) >= 1

        sse_events = _interaction_sse_events(run_id)
        assert sse_events
        assert sse_events[0].payload["interaction"]["kind"] == "vote"
    finally:
        settings.simulation_enabled = original


@pytest.mark.asyncio
async def test_price_surge_injection_changes_perception(client):
    """Inject price_surge → scheduler applies → agents perceive higher prices."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    captured: list[str] = []
    real_build = tick_runner._build_messages

    def _capture_build(persona: SimPersona, perception: str, *, text_mode: bool):
        if persona.agent_id == "zhao":
            captured.append(perception)
        return real_build(persona, perception, text_mode=text_mode)

    try:
        run_id = await _create_authed_run(client, username="int03-inject"
        )
        stay = {
            "action": "stay_here",
            "activity": "观望",
            "reason": "等待",
            "thought": "先看看。",
        }
        baseline_provider = _action_provider(stay, stay)
        strategy = ActivateOnlyStrategy(frozenset({"zhao"}))

        with (
            patch.object(settings, "max_parallel_agents", 1),
            patch(
                "agentcore.simulation.service.apply_schedule_fallback",
                new=_noop_schedule_fallback,
            ),
            patch(
                "agentcore.simulation.service.build_sim_provider",
                new=AsyncMock(return_value=(baseline_provider, _MOCK_CFG)),
            ),
            patch(
                "agentcore.api.routes.simulation.runs._service",
                side_effect=_service_factory(strategy),
            ),
        ):
            for _ in range(2):
                tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
                assert tick_res.status_code == 200, tick_res.text

        inject_res = await client.post(
            f"/v1/simulation/runs/{run_id}/inject",
            json={"event_type": "price_surge", "payload": {"multiplier": 2.0}},
        )
        assert inject_res.status_code == 202, inject_res.text

        captured.clear()
        post_provider = _action_provider(stay)
        with (
            patch.object(settings, "max_parallel_agents", 1),
            patch(
                "agentcore.simulation.service.apply_schedule_fallback",
                new=_noop_schedule_fallback,
            ),
            patch(
                "agentcore.simulation.service.build_sim_provider",
                new=AsyncMock(return_value=(post_provider, _MOCK_CFG)),
            ),
            patch(
                "agentcore.api.routes.simulation.runs._service",
                side_effect=_service_factory(strategy),
            ),
            patch(
                "agentcore.simulation.agents.tick_runner._build_messages",
                side_effect=_capture_build,
            ),
        ):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick_res.status_code == 200, tick_res.text
        snapshot = tick_res.json()["snapshot"]

        active_types = {event["event_type"] for event in snapshot.get("active_events", [])}
        assert "price_surge" in active_types
        assert snapshot["modifiers"]["market_price_multiplier"] == pytest.approx(2.0)

        assert captured, "expected captured perception for zhao"
        perception = captured[-1]
        assert "物价" in perception or "price_surge" in perception or "2.0" in perception
    finally:
        settings.simulation_enabled = original
