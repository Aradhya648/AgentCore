"""Thrash rebrand guard: reject cold redelegate after a thrashing worker.

When a recent worker finished thrashing (DEGRADED + ``source=ceiling_backstop``,
or zero_write/convergence cut with no landing) and a new cold task matches the
old topic / artifacts fingerprint, refuse silent rebrand — force
``continue_from_run_id`` or explicit ``force=true``.

Sibling to :mod:`isomorphic` (same drive admission layer). Does **not** auto-replan,
does not reuse ``note_completion_gap``, and does not expand isomorphic to arbitrary
same-role fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentcore.runtime.coordination.isomorphic import tasks_similar
from agentcore.runtime.engine.ceiling import CEILING_BACKSTOP_SOURCE

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec, RunState

# Cap recent thrash memory per conversation (FIFO).
_MAX_THRASH_RECORDS = 16


@dataclass(frozen=True, slots=True)
class ThrashRecord:
    """Fingerprint of a thrashing worker for rebrand collision checks."""

    run_id: str
    task: str
    artifacts: tuple[str, ...] = ()
    role: str = ""


# conversation_id → recent thrashing workers (本对话).
_thrash_by_conversation: dict[str, list[ThrashRecord]] = {}


def clear_thrash_registry(conversation_id: str | None = None) -> None:
    """Test helper: drop thrash memory for one conversation or all."""
    if conversation_id is None:
        _thrash_by_conversation.clear()
        return
    _thrash_by_conversation.pop(conversation_id, None)


def note_thrashing_worker(
    conversation_id: str,
    record: ThrashRecord,
) -> None:
    """Remember a thrashing worker for subsequent cold-delegate admission."""
    cid = (conversation_id or "").strip()
    if not cid or not record.run_id:
        return
    bucket = _thrash_by_conversation.setdefault(cid, [])
    # Newest wins on duplicate run_id.
    bucket[:] = [r for r in bucket if r.run_id != record.run_id]
    bucket.append(record)
    if len(bucket) > _MAX_THRASH_RECORDS:
        del bucket[: len(bucket) - _MAX_THRASH_RECORDS]


def recent_thrash_records(conversation_id: str) -> list[ThrashRecord]:
    """Copy of recent thrash records for ``conversation_id`` (oldest→newest)."""
    cid = (conversation_id or "").strip()
    if not cid:
        return []
    return list(_thrash_by_conversation.get(cid, ()))


def is_thrashing_run_state(state: RunState) -> bool:
    """True when a terminal RunState carries a thrashing backstop signal."""
    for esc in state.escalations or ():
        if not isinstance(esc, dict):
            continue
        if esc.get("source") == CEILING_BACKSTOP_SOURCE:
            return True
    # Form 2 fallback: zero_write/convergence cut with no landing (aligned path
    # always stamps ceiling_backstop; keep evidence-string check for harvest races).
    for esc in state.escalations or ():
        if not isinstance(esc, dict):
            continue
        evidence = str(esc.get("evidence") or "")
        if "zero_write_finalize" in evidence and not state.files_touched:
            return True
    return False


def thrash_record_from_node(
    node: RunSpec,
    state: RunState,
) -> ThrashRecord | None:
    """Build a :class:`ThrashRecord` when ``state`` is thrashing; else ``None``."""
    if not is_thrashing_run_state(state):
        return None
    artifacts: tuple[str, ...] = ()
    deliverable = getattr(node, "deliverable", None)
    if deliverable is not None:
        raw = getattr(deliverable, "artifacts", None) or ()
        artifacts = tuple(str(a) for a in raw if a)
    if not artifacts and state.files_touched:
        # Prefer declared artifacts; fall back to touched paths for fingerprint.
        artifacts = tuple(state.files_touched)
    return ThrashRecord(
        run_id=node.run_id,
        task=str(getattr(node, "task", None) or getattr(node, "objective", None) or ""),
        artifacts=artifacts,
        role=str(getattr(node, "role", None) or getattr(node, "agent_name", None) or ""),
    )


def _artifacts_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if not a or not b:
        return False
    na = {p.replace("\\", "/").lower().strip("/") for p in a}
    nb = {p.replace("\\", "/").lower().strip("/") for p in b}
    return bool(na & nb)


def _node_artifacts(node: Any) -> tuple[str, ...]:
    deliverable = getattr(node, "deliverable", None)
    if deliverable is None:
        return ()
    raw = getattr(deliverable, "artifacts", None) or ()
    return tuple(str(a) for a in raw if a)


def _node_task(node: Any) -> str:
    return str(getattr(node, "task", None) or getattr(node, "objective", None) or "")


def find_thrash_collision(
    new_plan: RunPlan,
    thrash_records: list[ThrashRecord] | tuple[ThrashRecord, ...],
) -> tuple[Any, ThrashRecord] | None:
    """Return ``(cold_node, thrash_record)`` when a cold task collides with thrash memory.

    Nodes that already set ``continue_from_run_id`` are not cold — skip them.
    Newest thrash record wins on ties.
    """
    if not thrash_records or not new_plan.nodes:
        return None
    # Newest first so the most recent thrash is preferred in the reject message.
    ordered = list(reversed(thrash_records))
    for nn in new_plan.nodes:
        continue_from = (getattr(nn, "continue_from_run_id", None) or "").strip()
        if continue_from:
            continue  # 续派 — not a cold rebrand
        n_task = _node_task(nn)
        n_arts = _node_artifacts(nn)
        for rec in ordered:
            if tasks_similar(n_task, rec.task) or _artifacts_overlap(n_arts, rec.artifacts):
                return nn, rec
    return None


def thrash_reject_message(record: ThrashRecord) -> str:
    """Structured rejection body forcing continue_from / force."""
    role = record.role or record.run_id
    return (
        "【再委派已拒绝·触顶换马甲】近期队员"
        f"（【{role}】`{record.run_id}`）因打转收口（DEGRADED / ceiling_backstop），"
        "本次冷派任务与旧题或同 artifacts 高度相似，禁止换马甲从零再读。"
        f"请对该 task 设 continue_from_run_id=`{record.run_id}` 带现场续派；"
        "若确需冷开新人，请显式传 force=true。"
    )


def record_thrashing_from_results(
    *,
    conversation_id: str,
    plan: RunPlan,
    results: dict[str, RunState],
) -> list[ThrashRecord]:
    """Scan terminal results and remember thrashing workers; return newly noted."""
    noted: list[ThrashRecord] = []
    for node in plan.nodes:
        state = results.get(node.run_id)
        if state is None:
            continue
        rec = thrash_record_from_node(node, state)
        if rec is None:
            continue
        note_thrashing_worker(conversation_id, rec)
        noted.append(rec)
    return noted
