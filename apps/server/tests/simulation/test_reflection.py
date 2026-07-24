"""Tests for reflection interval helper + goal anti-drift guard (BE-24 / WS-D)."""

from __future__ import annotations

from agentcore.simulation.agents.reflection import (
    REFLECTION_INTERVAL_TICKS,
    anchor_goal,
    should_reflect,
)
from agentcore.simulation.scenarios.town.config import LIN_PERSONA


def test_should_reflect_every_interval():
    assert not should_reflect(0)
    assert not should_reflect(1)
    assert should_reflect(REFLECTION_INTERVAL_TICKS)
    assert should_reflect(REFLECTION_INTERVAL_TICKS * 2)
    assert not should_reflect(REFLECTION_INTERVAL_TICKS + 1)


def test_anchor_goal_accepts_meaningful_change():
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", "改做镇上第一家法式甜品店") == "改做镇上第一家法式甜品店"


def test_anchor_goal_rejects_empty_or_trivial():
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", "") is None
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", "   ") is None
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", None) is None
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", "行") is None


def test_anchor_goal_rejects_unchanged_goal():
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", "攒钱交房租") is None
    assert anchor_goal(LIN_PERSONA, "攒钱交房租", "  攒钱交房租  ") is None


def test_anchor_goal_caps_runaway_length():
    result = anchor_goal(LIN_PERSONA, "x", "目标" * 60)
    assert result is not None
    assert len(result) <= 60
