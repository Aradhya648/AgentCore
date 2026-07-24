"""INT-02: full M2 pipeline — 10 agents × 5 ticks with mock LLM."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.config import settings
from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.llm.resolve import ModelConfig
from agentcore.simulation.agents import tick_runner
from agentcore.simulation.agents.activation import ActivateAllStrategy
from agentcore.simulation.service import SimulationService
from tests.integration.conftest import register_and_login

TEST_PASSWORD = "password123"
AGENT_COUNT = 10
_MOCK_CFG = ModelConfig(
    model="mock",
    base_url="http://mock",
    api_key="x",
    source="platform",
    purpose="sim.town",
)


def _stay_provider(*, rounds: int = 60) -> ScriptedProvider:
    payload = json.dumps(
        {"action": "stay_here", "activity": "测试", "reason": "x", "thought": "ok"},
        ensure_ascii=False,
    )
    return ScriptedProvider([[content_chunk(payload)] for _ in range(rounds)])


def _service_all_agents(repo):
    return SimulationService(repo, activation_strategy=ActivateAllStrategy())


@pytest.fixture(autouse=True)
def _force_llm_tick_mode(monkeypatch):
    """Pin LLM mode so local ``SIMULATION_SCRIPTED=true`` cannot mark the run
    scripted at create (and silently ignore the mock provider on tick).
    Also lift ``max_agents`` so a local cap of 5 cannot slice the town roster.
    """
    monkeypatch.setattr(settings, "simulation_scripted", False)
    monkeypatch.setattr(settings, "max_agents", AGENT_COUNT)


@pytest.mark.asyncio
async def test_m2_five_tick_full_pipeline(client, make_invite):
    """10 residents × 5 ticks: concurrency, persistence, memory, social."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    captured_perceptions: list[str] = []
    real_build = tick_runner._build_messages

    def _capture_build(persona, perception, *, text_mode):
        if persona.agent_id == "chen" and "tick 5" in perception:
            captured_perceptions.append(perception)
        return real_build(persona, perception, text_mode=text_mode)

    try:
        invite = await make_invite("SIM-M2-INT")
        await register_and_login(client, invite, "sim-m2-int", password=TEST_PASSWORD)

        # Patch create as well as ticks: without DeepSeek, create would otherwise
        # hit SimLlmNotConfigured; with SIMULATION_SCRIPTED that marks the run
        # scripted and bypasses the mock provider on every subsequent tick.
        with (
            patch(
                "agentcore.simulation.service.build_sim_provider",
                new=AsyncMock(return_value=(_stay_provider(), _MOCK_CFG)),
            ),
            patch("agentcore.api.routes.simulation.runs._service", side_effect=_service_all_agents),
            patch(
                "agentcore.simulation.agents.tick_runner._build_messages",
                side_effect=_capture_build,
            ),
        ):
            create_res = await client.post(
                "/v1/simulation/runs", json={"scenario": "town", "seed": 99}
            )
            assert create_res.status_code == 201
            run_id = create_res.json()["id"]

            snapshots = []
            for expected_tick in range(1, 6):
                tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
                assert tick_res.status_code == 200, tick_res.text
                snap = tick_res.json()["snapshot"]
                assert snap["tick"] == expected_tick
                snapshots.append(snap)

        # All 10 agents present each tick with decisions applied.
        for snap in snapshots:
            assert len(snap["agents"]) == 10
            for agent_state in snap["agents"].values():
                assert agent_state["activity"] == "测试"

        # Five tick snapshots persisted.
        for tick_number in range(1, 6):
            frame_res = await client.get(f"/v1/simulation/runs/{run_id}/ticks/{tick_number}")
            assert frame_res.status_code == 200
            assert frame_res.json()["tick_number"] == tick_number

        # Memory: tick 5 prompt for chen includes prior tick summaries.
        assert captured_perceptions, "expected perception capture on tick 5 for chen"
        perception_t5 = captured_perceptions[0]
        assert "【你的近期记忆】" in perception_t5
        assert "在 tick 1–4，" in perception_t5
        assert "连续4次" in perception_t5

        # Memory persisted on agent state after tick 5.
        chen_t5 = snapshots[4]["agents"]["chen"]
        assert len(chen_t5.get("tick_memories", [])) == 5
        assert chen_t5["tick_memories"][0].startswith("在 tick 1，")
        assert chen_t5["tick_memories"][-1].startswith("在 tick 5，")

        # Social: relationships evolve across ticks (colocation bonus).
        zhao_t1 = snapshots[0]["agents"]["zhao"]
        zhao_t5 = snapshots[4]["agents"]["zhao"]
        wang_rel_t1 = zhao_t1["relationships"]["wang"]
        wang_rel_t5 = zhao_t5["relationships"]["wang"]
        assert wang_rel_t5 > wang_rel_t1

        # Pause / resume: memories survive.
        pause_res = await client.post(f"/v1/simulation/runs/{run_id}/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["current_tick"] == 5

        resume_res = await client.post(f"/v1/simulation/runs/{run_id}/resume")
        assert resume_res.status_code == 200

        with (
            patch(
                "agentcore.simulation.service.build_sim_provider",
                new=AsyncMock(return_value=(_stay_provider(rounds=12), _MOCK_CFG)),
            ),
            patch("agentcore.api.routes.simulation.runs._service", side_effect=_service_all_agents),
        ):
            tick6_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick6_res.status_code == 200
        chen_t6 = tick6_res.json()["snapshot"]["agents"]["chen"]
        assert len(chen_t6.get("tick_memories", [])) == 6
        assert chen_t6["tick_memories"][0].startswith("在 tick 1，")

        frame5 = await client.get(f"/v1/simulation/runs/{run_id}/ticks/5")
        assert frame5.status_code == 200
        persisted_memories = frame5.json()["snapshot"]["agents"]["chen"]["tick_memories"]
        assert len(persisted_memories) == 5
    finally:
        settings.simulation_enabled = original
