"""BE-13 / WS-D: model routing tier + decision-kind strategy tests."""

from __future__ import annotations

from agentcore.simulation.llm import (
    SimDecisionKind,
    SimModelRouter,
    SimModelTier,
    default_routing_config,
    tier_for_decision,
)


def test_router_upgrades_critical_for_known_base():
    cfg = default_routing_config("deepseek-v4-flash")
    router = SimModelRouter(cfg)
    assert router.resolve(SimModelTier.ROUTINE) == "deepseek-v4-flash"
    assert router.resolve(SimModelTier.CRITICAL) == "deepseek-v4-pro"


def test_router_aliases_critical_for_unknown_base():
    cfg = default_routing_config("some-proxy-model")
    router = SimModelRouter(cfg)
    assert router.resolve(SimModelTier.ROUTINE) == "some-proxy-model"
    assert router.resolve(SimModelTier.CRITICAL) == "some-proxy-model"


def test_router_from_run_manifest():
    manifest = {"model_routing": {"routine_model": "a", "critical_model": "b"}}
    router = SimModelRouter.from_run_config(manifest, fallback="fallback")
    assert router.resolve(SimModelTier.ROUTINE) == "a"
    assert router.resolve(SimModelTier.CRITICAL) == "b"


def test_router_falls_back_when_manifest_missing():
    router = SimModelRouter.from_run_config({}, fallback="default-model")
    assert router.resolve() == "default-model"


def test_decision_kind_tiering_strategy():
    assert tier_for_decision(SimDecisionKind.ROUTINE_TICK) == SimModelTier.ROUTINE
    assert tier_for_decision(SimDecisionKind.INTERACTION) == SimModelTier.CRITICAL
    assert tier_for_decision(SimDecisionKind.REFLECTION) == SimModelTier.CRITICAL


def test_model_for_decision_routes_via_strategy():
    router = SimModelRouter(default_routing_config("deepseek-v4-flash"))
    assert router.model_for_decision(SimDecisionKind.ROUTINE_TICK) == "deepseek-v4-flash"
    assert router.model_for_decision(SimDecisionKind.INTERACTION) == "deepseek-v4-pro"
    assert router.model_for_decision(SimDecisionKind.REFLECTION) == "deepseek-v4-pro"


def test_explain_decision_is_human_readable():
    router = SimModelRouter(default_routing_config("deepseek-v4-flash"))
    text = router.explain_decision(SimDecisionKind.INTERACTION)
    assert "critical" in text
    assert "deepseek-v4-pro" in text
