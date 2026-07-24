"""INT-04: MVP acceptance — 10 residents × 20 ticks × 3 runs (mock LLM)."""

from __future__ import annotations

import json
import logging
from statistics import variance
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.config import settings
from agentcore.db.repositories.simulation import SimulationRepository
from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.llm.resolve import ModelConfig
from agentcore.simulation.agents.activation import ActivateAllStrategy
from agentcore.simulation.agents.memory import MAX_TICK_MEMORIES
from agentcore.simulation.experiment.manifest import RunManifest, build_run_manifest
from agentcore.simulation.service import SimulationService
from tests.integration.conftest import register_and_login

pytest_plugins = ["tests.integration.conftest"]

logger = logging.getLogger(__name__)

TEST_PASSWORD = "password123"
TICK_COUNT = 20
AGENT_COUNT = 10
RUN_SEEDS = (1001, 1002, 1003)
_MOCK_CFG = ModelConfig(
    model="mock",
    base_url="http://mock",
    api_key="x",
    source="platform",
    purpose="sim.town",
)


def _stay_provider(*, rounds: int = 300) -> ScriptedProvider:
    payload = json.dumps(
        {"action": "stay_here", "activity": "测试", "reason": "x", "thought": "ok"},
        ensure_ascii=False,
    )
    return ScriptedProvider([[content_chunk(payload)] for _ in range(rounds)])


@pytest.fixture(autouse=True)
def _mvp_env(monkeypatch):
    """INT-04 drives a mock LLM across the full 10-persona roster.

    Force the LLM tick path (a local ``.env`` ``SIMULATION_SCRIPTED=true`` would make
    ticks scripted and silently ignore the injected provider), and lift the roster cap
    so ``max_agents=5`` doesn't slice the town down to 5 — the ``== AGENT_COUNT`` asserts
    require all 10. Open registration is handled globally in
    ``tests/integration/conftest.py::_open_registration``.
    """
    monkeypatch.setattr(settings, "simulation_scripted", False)
    monkeypatch.setattr(settings, "max_agents", AGENT_COUNT)


def _service_all_agents(repo: SimulationRepository) -> SimulationService:
    return SimulationService(repo, activation_strategy=ActivateAllStrategy())


def _macro_summary(metrics_series: list[dict]) -> dict[str, float]:
    final = metrics_series[-1]
    trade_total = sum(float(m.get("trade_total_amount", 0.0)) for m in metrics_series)
    return {
        "avg_mood": float(final["avg_mood"]),
        "trade_total_amount": trade_total,
        "positive_relation_ratio": float(final["positive_relation_ratio"]),
    }


def _report_variance(label: str, values: list[float]) -> float:
    reported = 0.0 if len(values) < 2 else variance(values)
    logger.info("INT-04 variance %s: values=%s variance=%.6f", label, values, reported)
    return reported


@pytest.mark.asyncio
# 600 agent-tick × 3 轮 + 每 tick 真实 Postgres 持久化——全局 60s 兜底在共享 DB
# 有并行负载时会误杀（真实跑 40–90s 波动），单测放宽而非改全局。
@pytest.mark.timeout(240)
async def test_mvp_acceptance_ten_agents_twenty_ticks_three_runs(client, make_invite, session_factory):
    """10 residents × 20 ticks × 3 manifest-aligned runs; report macro variance (no threshold gate)."""
    original = settings.simulation_enabled
    settings.simulation_enabled = True
    base_manifest = build_run_manifest(scenario="town", seed=RUN_SEEDS[0])
    run_summaries: list[dict[str, float]] = []

    try:
        invite = await make_invite("INT04-MVP")
        await register_and_login(client, invite, "int04-mvp", password=TEST_PASSWORD)

        for run_index, seed in enumerate(RUN_SEEDS, start=1):
            manifest = base_manifest.model_copy(update={"seed": seed})
            create_res = await client.post(
                "/v1/simulation/runs",
                json={
                    "scenario": "town",
                    "seed": seed,
                    "manifest": manifest.model_dump(mode="json"),
                },
            )
            assert create_res.status_code == 201, create_res.text
            run_id = create_res.json()["id"]

            with (
                patch(
                    "agentcore.simulation.service.build_sim_provider",
                    new=AsyncMock(return_value=(_stay_provider(), _MOCK_CFG)),
                ),
                patch(
                    "agentcore.api.routes.simulation.runs._service",
                    side_effect=_service_all_agents,
                ),
            ):
                last_snapshot = None
                for expected_tick in range(1, TICK_COUNT + 1):
                    tick_res = await client.post(f"/v1/simulation/runs/{run_id}/tick")
                    assert tick_res.status_code == 200, tick_res.text
                    last_snapshot = tick_res.json()["snapshot"]
                    assert last_snapshot["tick"] == expected_tick

            assert last_snapshot is not None
            assert len(last_snapshot["agents"]) == AGENT_COUNT
            for agent_state in last_snapshot["agents"].values():
                assert agent_state["activity"] == "测试"
                memories = agent_state.get("tick_memories", [])
                assert len(memories) == min(TICK_COUNT, MAX_TICK_MEMORIES)
                assert memories[-1].startswith(f"在 tick {TICK_COUNT}，")

            async with session_factory() as session:
                repo = SimulationRepository(session)
                ticks = await repo.list_ticks_in_range(run_id, 1, TICK_COUNT)
                assert len(ticks) == TICK_COUNT
                agents = await repo.list_agents(run_id)
                assert len(agents) == AGENT_COUNT
                events = await repo.list_events_in_range(run_id, 1, TICK_COUNT)
                assert events, "expected sim_event rows for the run"

            for tick_number in range(1, TICK_COUNT + 1):
                frame_res = await client.get(f"/v1/simulation/runs/{run_id}/ticks/{tick_number}")
                assert frame_res.status_code == 200, frame_res.text
                assert frame_res.json()["tick_number"] == tick_number

            manifest_res = await client.get(f"/v1/simulation/runs/{run_id}/manifest")
            assert manifest_res.status_code == 200, manifest_res.text
            exported = RunManifest.model_validate(manifest_res.json()["manifest"])
            assert exported.scenario == manifest.scenario
            assert exported.seed == seed
            assert len(exported.personas) == len(manifest.personas)
            assert exported.regions == manifest.regions
            assert exported.temperature == manifest.temperature
            restored = RunManifest.model_validate(exported.model_dump(mode="json"))
            assert restored.model_dump(exclude={"created_at"}) == exported.model_dump(
                exclude={"created_at"}
            )

            metrics_res = await client.get(f"/v1/simulation/runs/{run_id}/metrics")
            assert metrics_res.status_code == 200, metrics_res.text
            metrics_body = metrics_res.json()
            assert metrics_body["run_id"] == run_id
            metrics_series = metrics_body["metrics"]
            assert len(metrics_series) == TICK_COUNT
            for idx, row in enumerate(metrics_series, start=1):
                assert row["tick"] == idx

            macro = _macro_summary(metrics_series)
            run_summaries.append(macro)
            logger.info(
                "INT-04 run %d seed=%d macro: avg_mood=%.4f trade_total=%.2f relation_density=%.4f",
                run_index,
                seed,
                macro["avg_mood"],
                macro["trade_total_amount"],
                macro["positive_relation_ratio"],
            )

        mood_var = _report_variance(
            "avg_mood", [row["avg_mood"] for row in run_summaries]
        )
        trade_var = _report_variance(
            "trade_total_amount", [row["trade_total_amount"] for row in run_summaries]
        )
        relation_var = _report_variance(
            "positive_relation_ratio",
            [row["positive_relation_ratio"] for row in run_summaries],
        )

        logger.info(
            "INT-04 MVP acceptance report: runs=%d ticks=%d agents=%d "
            "variance(avg_mood)=%.6f variance(trade_total)=%.6f variance(relation_density)=%.6f",
            len(RUN_SEEDS),
            TICK_COUNT,
            AGENT_COUNT,
            mood_var,
            trade_var,
            relation_var,
        )
    finally:
        settings.simulation_enabled = original
