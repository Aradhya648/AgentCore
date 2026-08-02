"""BE-11: tick persistence and pause/resume integration tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.config import settings
from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.llm.resolve import ModelConfig
from agentcore.simulation.agents.activation import ActivateAllStrategy
from agentcore.simulation.service import SimulationService
from agentcore.simulation.world.locations import REGION_POSITIONS
from tests.integration.conftest import register_and_login

TEST_PASSWORD = "password123"


def _stay_provider() -> ScriptedProvider:
    payload = json.dumps(
        {"action": "stay_here", "activity": "测试", "reason": "x", "thought": "ok"},
        ensure_ascii=False,
    )
    return ScriptedProvider([[content_chunk(payload)]])


@pytest.mark.asyncio
async def test_pause_blocks_tick(client):
    original = settings.simulation_enabled
    original_scripted = settings.simulation_scripted
    settings.simulation_enabled = True
    settings.simulation_scripted = False
    try:
        await register_and_login(client, "sim-pause", password=TEST_PASSWORD)
        create_res = await client.post("/v1/simulation/runs", json={"scenario": "town", "seed": 1})
        run_id = create_res.json()["id"]

        pause_res = await client.post(f"/v1/simulation/runs/{run_id}/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["status"] == "paused"

        mock_cfg = ModelConfig(
            model="mock", base_url="http://mock", api_key="x", source="platform", purpose="sim.town"
        )
        with patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(_stay_provider(), mock_cfg)),
        ):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick_res.status_code in (400, 422)

        resume_res = await client.post(f"/v1/simulation/runs/{run_id}/resume")
        assert resume_res.status_code == 200
        assert resume_res.json()["status"] == "running"
    finally:
        settings.simulation_enabled = original
        settings.simulation_scripted = original_scripted


@pytest.mark.asyncio
async def test_tick_persists_snapshot_and_agents(client):
    original = settings.simulation_enabled
    original_scripted = settings.simulation_scripted
    settings.simulation_enabled = True
    settings.simulation_scripted = False
    try:
        await register_and_login(client, "sim-persist", password=TEST_PASSWORD)
        create_res = await client.post("/v1/simulation/runs", json={"scenario": "town", "seed": 2})
        run_id = create_res.json()["id"]

        mock_cfg = ModelConfig(
            model="mock", base_url="http://mock", api_key="x", source="platform", purpose="sim.town"
        )
        with patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(_stay_provider(), mock_cfg)),
        ):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick_res.status_code == 200
        snapshot = tick_res.json()["snapshot"]
        assert snapshot["tick"] == 1
        chen = snapshot["agents"]["chen"]
        assert chen["activity"] == "测试"
        assert chen.get("relationships")

        frame_res = await client.get(f"/v1/simulation/runs/{run_id}/ticks/1")
        assert frame_res.status_code == 200
        assert frame_res.json()["snapshot"]["agents"]["chen"]["location"] in REGION_POSITIONS
    finally:
        settings.simulation_enabled = original
        settings.simulation_scripted = original_scripted


@pytest.mark.asyncio
async def test_five_ticks_pause_resume_advances_to_tick_six(client):
    """BE-11 acceptance: 5 persisted snapshots; resume continues at tick 6."""
    original = settings.simulation_enabled
    original_scripted = settings.simulation_scripted
    settings.simulation_enabled = True
    settings.simulation_scripted = False
    try:
        await register_and_login(client, "sim-5tick", password=TEST_PASSWORD)
        create_res = await client.post("/v1/simulation/runs", json={"scenario": "town", "seed": 4})
        run_id = create_res.json()["id"]

        mock_cfg = ModelConfig(
            model="mock", base_url="http://mock", api_key="x", source="platform", purpose="sim.town"
        )
        with patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(_stay_provider(), mock_cfg)),
        ):
            for expected in range(1, 6):
                tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
                assert tick_res.status_code == 200, tick_res.text
                assert tick_res.json()["snapshot"]["tick"] == expected

        for tick_number in range(1, 6):
            frame_res = await client.get(f"/v1/simulation/runs/{run_id}/ticks/{tick_number}")
            assert frame_res.status_code == 200
            assert frame_res.json()["tick_number"] == tick_number

        pause_res = await client.post(f"/v1/simulation/runs/{run_id}/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["current_tick"] == 5

        resume_res = await client.post(f"/v1/simulation/runs/{run_id}/resume")
        assert resume_res.status_code == 200

        with patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(_stay_provider(), mock_cfg)),
        ):
            tick6_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick6_res.status_code == 200
        assert tick6_res.json()["snapshot"]["tick"] == 6

        frame6 = await client.get(f"/v1/simulation/runs/{run_id}/ticks/6")
        assert frame6.status_code == 200
    finally:
        settings.simulation_enabled = original
        settings.simulation_scripted = original_scripted


@pytest.mark.asyncio
async def test_social_state_persists_across_ticks(client):
    """BE-14 acceptance: mood/relationship deltas survive tick persistence."""
    original = settings.simulation_enabled
    original_scripted = settings.simulation_scripted
    settings.simulation_enabled = True
    settings.simulation_scripted = False
    try:
        await register_and_login(client, "sim-social", password=TEST_PASSWORD)
        create_res = await client.post("/v1/simulation/runs", json={"scenario": "town", "seed": 5})
        run_id = create_res.json()["id"]

        mock_cfg = ModelConfig(
            model="mock", base_url="http://mock", api_key="x", source="platform", purpose="sim.town"
        )
        with patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(_stay_provider(), mock_cfg)),
        ):
            first = await client.post(f"/v1/simulation/runs/{run_id}/tick")
            second = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert first.status_code == 200 and second.status_code == 200

        zhao_t1 = first.json()["snapshot"]["agents"]["zhao"]
        zhao_t2 = second.json()["snapshot"]["agents"]["zhao"]
        wang_rel_t1 = zhao_t1["relationships"]["wang"]
        wang_rel_t2 = zhao_t2["relationships"]["wang"]
        assert wang_rel_t2 > wang_rel_t1

        frame_res = await client.get(f"/v1/simulation/runs/{run_id}/ticks/2")
        assert frame_res.status_code == 200
        persisted = frame_res.json()["snapshot"]["agents"]["zhao"]
        assert persisted["relationships"]["wang"] == wang_rel_t2
    finally:
        settings.simulation_enabled = original
        settings.simulation_scripted = original_scripted


@pytest.mark.asyncio
async def test_activate_all_strategy_runs_full_batch(client):
    """ActivateAllStrategy still advances all 10 agents."""
    original = settings.simulation_enabled
    original_scripted = settings.simulation_scripted
    settings.simulation_enabled = True
    settings.simulation_scripted = False
    try:
        await register_and_login(client, "sim-all", password=TEST_PASSWORD)
        create_res = await client.post("/v1/simulation/runs", json={"scenario": "town", "seed": 3})
        run_id = create_res.json()["id"]

        mock_cfg = ModelConfig(
            model="mock", base_url="http://mock", api_key="x", source="platform", purpose="sim.town"
        )

        def _service(repo):
            return SimulationService(
                repo,
                activation_strategy=ActivateAllStrategy(),
            )

        with (
            patch(
                "agentcore.simulation.service.build_sim_provider",
                new=AsyncMock(return_value=(_stay_provider(), mock_cfg)),
            ),
            patch("agentcore.api.routes.simulation.runs._service", side_effect=_service),
        ):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick_res.status_code == 200
        assert len(tick_res.json()["snapshot"]["agents"]) == 10
    finally:
        settings.simulation_enabled = original
        settings.simulation_scripted = original_scripted
