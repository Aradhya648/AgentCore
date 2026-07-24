"""期编排器单测。"""

from __future__ import annotations

from agentcore.simulation.scenarios.show.cast import LUYE, SHENWAN, XUANAN
from agentcore.simulation.scenarios.show.config import SHOW_NIGHT_REGION
from agentcore.simulation.show.orchestrator import (
    episode_tick_span,
    gate_at_tick,
    plan_episode,
)
from agentcore.simulation.show.rules import new_season_state


def test_episode_tick_spans_contiguous():
    assert episode_tick_span(1) == (0, 119)
    assert episode_tick_span(2) == (120, 239)
    assert episode_tick_span(3) == (240, 359)


def test_plan_episode3_date_pairs_and_quiz():
    state = new_season_state(seed=42)
    plan = plan_episode(state, 3)
    assert plan.quiz_focus == XUANAN
    assert plan.awkward_kind is not None
    assert plan.night_location == SHOW_NIGHT_REGION
    # Forced B–C pair
    assert (LUYE, XUANAN) in plan.date_pairs or (XUANAN, LUYE) in plan.date_pairs
    assert plan.tick_start == 240
    assert plan.tick_end == 359
    # Gates cover full span
    covered = set()
    for start, end in plan.gates.values():
        for t in range(start, end + 1):
            covered.add(t)
    assert covered == set(range(plan.tick_start, plan.tick_end + 1))
    assert gate_at_tick(plan, plan.gates["night"][0]) == "night"


def test_plan_episode2_forces_ab_date():
    state = new_season_state(seed=1)
    plan = plan_episode(state, 2)
    assert (SHENWAN, LUYE) in plan.date_pairs or (LUYE, SHENWAN) in plan.date_pairs


def test_same_seed_reproducible():
    a = plan_episode(new_season_state(seed=99), 3)
    b = plan_episode(new_season_state(seed=99), 3)
    assert a.date_pairs == b.date_pairs
    assert a.date_locations == b.date_locations
    assert a.awkward_kind == b.awkward_kind


def test_allowed_picks_exclude_self():
    state = new_season_state(seed=0)
    plan = plan_episode(state, 1)
    for voter, targets in plan.allowed_picks.items():
        assert voter not in targets
        assert len(targets) >= 1
