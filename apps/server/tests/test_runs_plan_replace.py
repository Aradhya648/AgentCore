"""RunPlan.replace semantics: replaces_run_id rewrites downstream depends_on."""

from agentcore.runtime.runs.plan import RunPlan, clear_revivable_skips
from agentcore.runtime.runs.types import RunKind, RunPhase, RunPolicy, RunSpec, RunState


def _spec(
    run_id: str,
    depends_on: list[str] | None = None,
    *,
    replaces_run_id: str | None = None,
    on_failure: str = "retry",
) -> RunSpec:
    return RunSpec(
        run_id=run_id,
        agent_id=run_id,
        agent_name=run_id,
        kind=RunKind.AGENT,
        task=f"task-{run_id}",
        role=run_id,
        depends_on=list(depends_on or []),
        replaces_run_id=replaces_run_id,
        policy=RunPolicy(on_failure=on_failure),  # type: ignore[arg-type]
    )


def test_add_with_replaces_rewrites_downstream_depends_on():
    plan = RunPlan()
    plan.add(_spec("r1"))
    plan.add(_spec("r2"))
    plan.add(_spec("writer", ["r1", "r2"]))

    plan.add(_spec("r1b", replaces_run_id="r1"))

    writer = plan.by_id("writer")
    assert writer is not None
    assert writer.depends_on == ["r1b", "r2"]
    assert plan.by_id("r1b") is not None
    assert plan.by_id("r1b").replaces_run_id == "r1"


def test_rewrite_dedupes_when_new_id_already_listed():
    plan = RunPlan()
    plan.add(_spec("r1"))
    plan.add(_spec("r1b"))
    plan.add(_spec("writer", ["r1", "r1b"]))

    touched = plan.rewrite_depends_for_replace(_spec("r1b", replaces_run_id="r1"))
    assert touched == ["writer"]
    assert plan.by_id("writer").depends_on == ["r1b"]


def test_rewrite_no_op_without_replaces_or_matching_dep():
    plan = RunPlan()
    plan.add(_spec("r1"))
    plan.add(_spec("writer", ["r1"]))
    assert plan.rewrite_depends_for_replace(_spec("x", replaces_run_id=None)) == []
    assert plan.by_id("writer").depends_on == ["r1"]
    assert plan.rewrite_depends_for_replace(_spec("x", replaces_run_id="missing")) == []
    assert plan.by_id("writer").depends_on == ["r1"]


def test_clear_revivable_skips_after_replaces_rewrites_edge():
    """SKIPPED synth seed clears once depends_on no longer points at FAILED upstream."""
    plan = RunPlan()
    plan.add(_spec("pr"))
    plan.add(_spec("legal"))
    plan.add(_spec("synth", ["pr", "legal"]))
    completed = {
        "pr": RunState(phase=RunPhase.FAILED, error="contract"),
        "legal": RunState(phase=RunPhase.COMPLETED, content="ok"),
        "synth": RunState(phase=RunPhase.SKIPPED),
    }
    plan.add(_spec("pr_b", replaces_run_id="pr"))
    cleared = clear_revivable_skips(plan, completed)
    assert cleared == ["synth"]
    assert "synth" not in completed
    assert plan.by_id("synth").depends_on == ["pr_b", "legal"]
    # Failed original stays seeded; only the cascade-skipped dependent is revived.
    assert completed["pr"].phase is RunPhase.FAILED


def test_clear_revivable_skips_transitive():
    plan = RunPlan()
    plan.add(_spec("a"))
    plan.add(_spec("b", ["a"]))
    plan.add(_spec("c", ["b"]))
    completed = {
        "a": RunState(phase=RunPhase.FAILED, error="boom"),
        "b": RunState(phase=RunPhase.SKIPPED),
        "c": RunState(phase=RunPhase.SKIPPED),
    }
    plan.add(_spec("a2", replaces_run_id="a"))
    cleared = clear_revivable_skips(plan, completed)
    assert set(cleared) == {"b", "c"}
    assert "b" not in completed and "c" not in completed
