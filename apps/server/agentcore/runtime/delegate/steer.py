"""Plan steer / gate_notes / downstream scoping and journal snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan

_GATE_CONCLUSION_CHARS = 200


def record_plan_snapshot(plan: RunPlan) -> None:
    """Journal the current plan as a ``plan_snapshot`` fact."""
    from agentcore.runtime.facts import record_turn_fact
    from agentcore.runtime.runs.serialize import plan_snapshot_fact

    record_turn_fact(plan_snapshot_fact(plan))


def apply_steer(plan: RunPlan, completed: dict, checkpoint_ids: set[str], note: str) -> None:
    """Inject a plan_review ``adjust`` / kickoff CONTINUE|ADJUST note onto not-yet-run targets.

    With non-empty ``checkpoint_ids`` (plan_review), targets are the transitive
    dependents of those checkpoint nodes. With empty roots (team_preview — no worker
    has run yet), every not-yet-completed node is steered.
    """
    targets = (
        downstream_of(plan, checkpoint_ids)
        if checkpoint_ids
        else {n.run_id for n in plan.nodes if n.run_id not in completed}
    )
    block = f"- {note}"
    for node in plan.nodes:
        if node.run_id in completed or node.run_id not in targets:
            continue
        node.steer = f"{node.steer}\n{block}" if node.steer else block
    record_plan_snapshot(plan)


def compress_ceo_review_for_gate(review: dict[str, Any] | None) -> str | None:
    """Compress an llm ``ceo_review`` into gate_notes body; ``None`` if should not inject.

    Only ``source=="llm"`` compresses. Deterministic / missing / old frames → no inject
    (CONTINUE behaves as before). Template: 放行前缀 + 结论~200 字 + Top3 风险 + Top2 建议.
    """
    if not isinstance(review, dict) or review.get("source") != "llm":
        return None
    conclusion = str(review.get("conclusion") or "").strip()
    if len(conclusion) > _GATE_CONCLUSION_CHARS:
        conclusion = conclusion[:_GATE_CONCLUSION_CHARS] + "…"
    risks = [str(r).strip() for r in (review.get("risks") or []) if str(r).strip()][:3]
    suggestions = [
        str(s).strip() for s in (review.get("suggestions") or []) if str(s).strip()
    ][:2]
    parts = ["（用户已放行；以下为注意事项，非否决，请据此推进，勿停工另起炉灶）"]
    if conclusion:
        parts.append(f"结论：{conclusion}")
    if risks:
        parts.append("风险：\n" + "\n".join(f"- {r}" for r in risks))
    if suggestions:
        parts.append("建议：\n" + "\n".join(f"- {s}" for s in suggestions))
    body = "\n".join(parts).strip()
    return body or None


def apply_gate_notes(
    plan: RunPlan, completed: dict, checkpoint_ids: set[str], notes: str
) -> None:
    """REPLACE ``gate_notes`` on not-yet-run targets (plan_review CONTINUE · llm 把关).

    Scoped like :func:`apply_steer` (transitive dependents of checkpoint roots, or all
    unrun nodes when roots empty). Does **not** touch ``steer``.
    """
    text = (notes or "").strip()
    if not text:
        return
    targets = (
        downstream_of(plan, checkpoint_ids)
        if checkpoint_ids
        else {n.run_id for n in plan.nodes if n.run_id not in completed}
    )
    for node in plan.nodes:
        if node.run_id in completed or node.run_id not in targets:
            continue
        node.gate_notes = text  # REPLACE（禁止 append / 复用 steer）
    record_plan_snapshot(plan)


def downstream_of(plan: RunPlan, roots: set[str]) -> set[str]:
    """Run ids that (transitively) ``depends_on`` any node in ``roots``."""
    downstream: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in plan.nodes:
            if node.run_id in downstream or node.run_id in roots:
                continue
            if any(dep in roots or dep in downstream for dep in node.depends_on):
                downstream.add(node.run_id)
                changed = True
    return downstream
