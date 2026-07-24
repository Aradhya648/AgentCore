"""Unit tests for run manifest (BE-27)."""

from __future__ import annotations

from agentcore.simulation.experiment.manifest import RunManifest, build_run_manifest
from agentcore.simulation.llm import default_routing_config
from agentcore.simulation.scenarios.town.config import TOWN_CONFIG, TOWN_PERSONAS


def test_build_run_manifest_includes_repro_fields():
    routing = default_routing_config("deepseek-v4-flash")
    manifest = build_run_manifest(
        scenario="town",
        seed=42,
        model_routing=routing,
        personas=TOWN_PERSONAS,
        regions=TOWN_CONFIG.regions,
    )
    assert manifest.seed == 42
    assert len(manifest.personas) == len(TOWN_PERSONAS)
    assert manifest.regions == list(TOWN_CONFIG.regions)
    assert manifest.model_routing is not None
    assert manifest.model_routing.routine_model == "deepseek-v4-flash"
    assert manifest.temperature == 0.8


def test_run_manifest_roundtrip_json():
    manifest = build_run_manifest(scenario="town", seed=7)
    restored = RunManifest.model_validate(manifest.model_dump(mode="json"))
    assert restored.seed == manifest.seed
    assert restored.personas[0].agent_id == manifest.personas[0].agent_id
