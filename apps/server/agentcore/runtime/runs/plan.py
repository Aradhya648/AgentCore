"""RunPlan — a turn's set of Run nodes + their dependency wave order.

Every orchestration shape is a *degenerate* RunPlan, so the scheduler has one
input shape and single / parallel / DAG become data, not code paths:

- single worker     = one node, no deps;
- parallel batch    = N independent nodes;
- DAG               = nodes wired by ``depends_on``;
- adaptive (阶段2)  = an empty plan a captain grows via :meth:`add`.

→ 见设计: docs/03-AI核心/执行引擎架构设计.md §八（Run 模型）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentcore.runtime.runs.types import RunOrigin, RunPhase, RunSpec, RunState


class RunPlanError(ValueError):
    """A plan can't be scheduled: a duplicate ``run_id``, an unknown
    ``depends_on`` edge, or a dependency cycle."""


def clear_revivable_skips(plan: RunPlan, completed: dict[str, RunState]) -> list[str]:
    """Drop ``SKIPPED`` seed states whose cascade reason no longer holds.

    After ``replaces_run_id`` rewrites ``depends_on`` off a failed upstream, a
    cascade-skipped downstream must leave ``seed_completed`` so the resumed
    ``WaveScheduler`` can wait on the replacement. Walks to a fixed point so
    transitive skips (A→B→C) clear once their blocking ancestors clear.

    Returns the ``run_id``s removed (stable insertion order).
    """
    cleared: list[str] = []
    changed = True
    while changed:
        changed = False
        for rid, state in list(completed.items()):
            if state.phase is not RunPhase.SKIPPED:
                continue
            node = plan.by_id(rid)
            if node is None:
                continue
            if _seed_still_cascade_blocked(plan, node, completed):
                continue
            del completed[rid]
            cleared.append(rid)
            changed = True
    return cleared


def _seed_still_cascade_blocked(
    plan: RunPlan,
    node: RunSpec,
    completed: dict[str, RunState],
) -> bool:
    """Mirror wave cascade rules for seed maps: FAILED+{skip,retry} or SKIPPED dep."""
    for dep_id in node.depends_on:
        dep_state = completed.get(dep_id)
        if dep_state is None:
            continue
        if dep_state.phase is RunPhase.SKIPPED:
            return True
        if dep_state.phase is not RunPhase.FAILED:
            continue
        dep = plan.by_id(dep_id)
        if dep is not None and dep.policy.on_failure in ("skip", "retry"):
            return True
    return False


@dataclass
class RunPlan:
    """An ordered bag of :class:`RunSpec` nodes plus where they came from.

    Mutable on purpose: a captain may append nodes mid-run (``origin =
    CAPTAIN``, 阶段2). The plan owns only structure (nodes + edges); execution
    state lives in each node's :class:`RunState`, driven by the scheduler.
    """

    nodes: list[RunSpec] = field(default_factory=list)
    origin: RunOrigin = RunOrigin.TEMPLATE
    # Non-fatal build-time heads-up for the CEO (e.g. suspect_missing_dep): a task
    # mentions upstream output but declares no ``depends_on``. Surfaced once through
    # the coordination injection channel (搭车, no extra wake) — never blocks the plan.
    advisories: list[str] = field(default_factory=list)
    # User-workflow mode: lock topology (no add / dependency rewrites); text steers OK.
    topology_lock: bool = False
    workflow_id: str | None = None
    workflow_version: int | None = None

    def add(self, spec: RunSpec) -> RunSpec:
        """Append one node. A duplicate ``run_id`` is a caller bug (ids are
        minted by the caller) and raises rather than silently shadowing.

        When ``spec.replaces_run_id`` is set (协调补派 / 冷回落接手), rewrite every
        other node's ``depends_on`` entry that names the failed run so downstream
        waits on the replacement instead of treating the failure as terminal.
        """
        if any(n.run_id == spec.run_id for n in self.nodes):
            raise RunPlanError(f"duplicate run_id: {spec.run_id}")
        self.nodes.append(spec)
        if spec.replaces_run_id:
            self.rewrite_depends_for_replace(spec)
        return spec

    def rewrite_depends_for_replace(self, replacement: RunSpec) -> list[str]:
        """Point dependents of ``replacement.replaces_run_id`` at ``replacement.run_id``.

        Returns the ``run_id``s whose ``depends_on`` changed (stable insertion order).
        No-op when ``replaces_run_id`` is missing or equals the new id.
        """
        old = (replacement.replaces_run_id or "").strip()
        new = replacement.run_id
        if not old or old == new:
            return []
        touched: list[str] = []
        for node in self.nodes:
            if node.run_id == new:
                continue
            deps = node.depends_on
            if old not in deps:
                continue
            rewritten: list[str] = []
            seen: set[str] = set()
            for dep in deps:
                mapped = new if dep == old else dep
                if mapped in seen:
                    continue
                seen.add(mapped)
                rewritten.append(mapped)
            node.depends_on = rewritten
            touched.append(node.run_id)
        return touched

    def by_id(self, run_id: str) -> RunSpec | None:
        return next((n for n in self.nodes if n.run_id == run_id), None)

    def waves(self) -> list[list[RunSpec]]:
        """Group nodes into dependency waves (Kahn-style topological layering).

        Wave 0 = nodes with no unmet deps; each later wave = nodes whose deps all
        landed in an earlier wave. Node order *within* a wave preserves insertion
        order, so a plan with no deps reproduces declaration order.

        Raises :class:`RunPlanError` on an unknown edge (a ``depends_on`` naming a
        run not in the plan) or a cycle (nodes remain but none can advance).
        """
        ids = {n.run_id for n in self.nodes}
        for n in self.nodes:
            for dep in n.depends_on:
                if dep not in ids:
                    raise RunPlanError(f"run {n.run_id} depends on unknown run {dep}")

        resolved: set[str] = set()
        waves: list[list[RunSpec]] = []
        remaining = list(self.nodes)
        while remaining:
            wave = [n for n in remaining if all(d in resolved for d in n.depends_on)]
            if not wave:
                stuck = ", ".join(n.run_id for n in remaining)
                raise RunPlanError(f"dependency cycle among runs: {stuck}")
            waves.append(wave)
            resolved.update(n.run_id for n in wave)
            remaining = [n for n in remaining if n.run_id not in resolved]
        return waves
