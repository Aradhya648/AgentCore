"""Unit tests for tick replay assembly (BE-28)."""

from __future__ import annotations

import pytest

from agentcore.core.errors import ValidationError
from agentcore.runtime.events import EventType
from agentcore.simulation.service import _replay_event_type


def test_replay_event_type_maps_sim_and_interaction_kinds():
    assert _replay_event_type("sim.tick_started") == EventType.SIM_TICK_STARTED
    assert _replay_event_type("trade") == EventType.SIM_INTERACTION


def test_replay_event_type_rejects_unknown():
    with pytest.raises(ValidationError):
        _replay_event_type("not.a.real.event")
