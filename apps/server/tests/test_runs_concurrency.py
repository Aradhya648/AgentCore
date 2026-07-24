"""Tests for the tree-wide concurrency budget primitives (ContextVar + child split).

The budget itself is *enforced* by the WaveScheduler (it divides by ``child_budget``
and caps concurrent dispatch); these cover the primitives in isolation. The
end-to-end「nested fan-out can't multiply past the budget」invariant is exercised in
test_runs_wave.py::test_nested_fanout_respects_tree_budget.
"""

from agentcore.runtime.runs.concurrency import (
    child_budget,
    current_budget,
    reset_budget,
    set_budget,
)
from agentcore.runtime.runs.constants import MAX_PARALLEL_DELEGATIONS


def test_default_budget_is_the_tree_cap():
    assert current_budget() == MAX_PARALLEL_DELEGATIONS


def test_set_and_reset_budget_round_trips():
    token = set_budget(3)
    try:
        assert current_budget() == 3
    finally:
        reset_budget(token)
    assert current_budget() == MAX_PARALLEL_DELEGATIONS


def test_budget_floor_is_one():
    token = set_budget(0)
    try:
        assert current_budget() == 1
    finally:
        reset_budget(token)


def test_child_budget_divides_by_width():
    token = set_budget(8)
    try:
        assert child_budget(8) == 1
        assert child_budget(3) == 2  # 8 // 3
        assert child_budget(1) == 8
        assert child_budget(0) == 8  # width floored to 1
    finally:
        reset_budget(token)
