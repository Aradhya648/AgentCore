"""M1 API smoke: create run → advance tick (mock LLM) → agent moves."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.config import settings
from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.llm.resolve import ModelConfig
from agentcore.simulation.world.locations import REGION_POSITIONS
from tests.integration.conftest import register_and_login

TEST_PASSWORD = "password123"


def _move_to_market_provider(*, rounds: int = 12) -> ScriptedProvider:
    payload = json.dumps(
        {
            "action": "move_to",
            "destination": "市场",
            "reason": "去进面粉",
            "thought": "得赶紧去市场进原料。",
        },
        ensure_ascii=False,
    )
    return ScriptedProvider([[content_chunk(payload)] for _ in range(rounds)])


@pytest.mark.asyncio
async def test_simulation_api_smoke_mock_llm(client):
    """REST closed loop with mock LLM — no real upstream required."""
    original = settings.simulation_enabled
    original_scripted = settings.simulation_scripted
    settings.simulation_enabled = True
    settings.simulation_scripted = False
    try:
        await register_and_login(client, "sim-smoke", password=TEST_PASSWORD)

        create_res = await client.post(
            "/v1/simulation/runs",
            json={"scenario": "town", "seed": 42},
        )
        assert create_res.status_code == 201, create_res.text
        run = create_res.json()
        run_id = run["id"]

        mock_cfg = ModelConfig(
            model="mock",
            base_url="http://mock",
            api_key="x",
            source="platform",
            purpose="sim.town",
        )
        with patch(
            "agentcore.simulation.service.build_sim_provider",
            new=AsyncMock(return_value=(_move_to_market_provider(), mock_cfg)),
        ):
            tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
        assert tick_res.status_code == 200, tick_res.text
        snapshot = tick_res.json()["snapshot"]
        assert snapshot["tick"] == 1
        assert len(snapshot["agents"]) == 10
        # Agents run in agent_id order; mock moves each to 市场.
        chen = snapshot["agents"]["chen"]
        assert chen["location"] == "市场"
        assert chen["position"]["x"] == REGION_POSITIONS["市场"].x

        frame_res = await client.get(f"/v1/simulation/runs/{run_id}/ticks/1")
        assert frame_res.status_code == 200
        assert frame_res.json()["snapshot"]["agents"]["chen"]["location"] == "市场"
    finally:
        settings.simulation_enabled = original
        settings.simulation_scripted = original_scripted
