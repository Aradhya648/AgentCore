"""Unit tests for simulation cost / demo size guards (no LLM)."""

from __future__ import annotations

import pytest

from agentcore.config.simulation import SimulationSettings
from agentcore.core.errors import ValidationError
from agentcore.simulation.cost_guards import ensure_under_max_ticks, slice_personas_for_run
from agentcore.simulation.scenarios.town.config import TOWN_PERSONAS


def test_simulation_settings_cost_guard_defaults():
    s = SimulationSettings()
    assert s.max_agents == 5
    assert s.max_ticks == 48
    assert s.max_parallel_agents == 6
    assert s.simulation_scripted is False


def test_slice_personas_caps_at_max_agents():
    assert len(TOWN_PERSONAS) > 5
    sliced = slice_personas_for_run(TOWN_PERSONAS, max_agents=5)
    assert len(sliced) == 5
    assert [p.agent_id for p in sliced] == [p.agent_id for p in TOWN_PERSONAS[:5]]


def test_slice_personas_keeps_short_roster():
    roster = TOWN_PERSONAS[:2]
    assert slice_personas_for_run(roster, max_agents=5) == roster


def test_ensure_under_max_ticks_allows_below_cap():
    ensure_under_max_ticks(0, max_ticks=48)
    ensure_under_max_ticks(47, max_ticks=48)


def test_ensure_under_max_ticks_rejects_at_cap():
    with pytest.raises(ValidationError, match="max_ticks"):
        ensure_under_max_ticks(48, max_ticks=48)
    with pytest.raises(ValidationError, match="max_ticks"):
        ensure_under_max_ticks(49, max_ticks=48)
