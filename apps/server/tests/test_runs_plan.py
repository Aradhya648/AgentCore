"""Tests for RunPlan topology: wave layering, dup/unknown-edge/cycle guards.

Pure structure — no scheduler, no executor, no LLM. Covers the single input
shape the WaveScheduler consumes (single / parallel / DAG all reduce to a
RunPlan whose ``waves()`` falls out of the ``depends_on`` edges).
"""

import pytest

from agentcore.runtime.runs.plan import RunPlan, RunPlanError
from agentcore.runtime.runs.types import RunSpec


def _spec(run_id: str, deps: tuple[str, ...] = ()) -> RunSpec:
    return RunSpec(run_id=run_id, task="t", agent_id=run_id, role=run_id, depends_on=list(deps))


def test_no_deps_is_one_wave_in_declaration_order():
    plan = RunPlan()
    for x in ("a", "b", "c"):
        plan.add(_spec(x))
    waves = plan.waves()
    assert len(waves) == 1
    assert [n.run_id for n in waves[0]] == ["a", "b", "c"]


def test_linear_chain_layers_one_per_wave():
    plan = RunPlan()
    plan.add(_spec("a"))
    plan.add(_spec("b", ("a",)))
    plan.add(_spec("c", ("b",)))
    assert [[n.run_id for n in w] for w in plan.waves()] == [["a"], ["b"], ["c"]]


def test_diamond_groups_middle_layer():
    plan = RunPlan()
    plan.add(_spec("a"))
    plan.add(_spec("b", ("a",)))
    plan.add(_spec("c", ("a",)))
    plan.add(_spec("d", ("b", "c")))
    waves = plan.waves()
    assert [n.run_id for n in waves[0]] == ["a"]
    assert sorted(n.run_id for n in waves[1]) == ["b", "c"]
    assert [n.run_id for n in waves[2]] == ["d"]


def test_add_duplicate_run_id_raises():
    plan = RunPlan()
    plan.add(_spec("a"))
    with pytest.raises(RunPlanError):
        plan.add(_spec("a"))


def test_unknown_edge_raises():
    plan = RunPlan()
    plan.add(_spec("a", ("ghost",)))
    with pytest.raises(RunPlanError):
        plan.waves()


def test_cycle_raises():
    plan = RunPlan()
    plan.add(_spec("a", ("b",)))
    plan.add(_spec("b", ("a",)))
    with pytest.raises(RunPlanError):
        plan.waves()


def test_by_id_lookup():
    plan = RunPlan()
    plan.add(_spec("a"))
    assert plan.by_id("a").run_id == "a"
    assert plan.by_id("missing") is None
