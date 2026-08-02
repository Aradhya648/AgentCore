"""Mid-coordination append overlap guard + C3 dispatch ownership.

When the live graph still has incomplete nodes, a secondary ``delegate`` that
claims the same **seat** (normalized role-name equality) is rejected.

**Seat model**: a seat is ``_norm_role(role)`` — whitespace-stripped lowercase
equality only. Shared job suffixes / CJK prefixes / edit distance do **not**
merge seats (痛点调研员 ≠ 定价调研员; 前端工程师 ≠ 测试工程师).

**Vacated seats**: FAILED / CANCELLED / SKIPPED terminals free their seat.
A new node with the same seat and no incomplete same-seat peer is auto-filled
with ``replaces_run_id`` (file lock transfer + downstream depends_on rewrite via
the existing replaces pipeline). Successfully COMPLETED seats stay occupied
until explicit ``replaces_run_id`` / ``force``.

**C3 file side**: deliverable artifacts consult the session ownership ledger
(including completed owners). ``has_incomplete_nodes`` no longer short-circuits
file checks — all_completed still blocks racing a held final path unless
``replaces_run_id`` / ``continue_from_run_id`` / ancestor / ``force`` transfers.
Role-only overlap still requires incomplete live nodes.

Same-batch sibling artifact crosses are rejected at dispatch (name the pair),
**before** durable ``run_plan`` emit (admit → commit → execute).

Ownership keys are **concrete file** ``artifacts`` only — directory prefixes /
``artifact_dir`` / globs are acceptance coverage, never exclusive claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentcore.runtime.coordination.isomorphic import _node_role, _node_task
from agentcore.workspace.write_claims import (
    WriteCoordinator,
    file_ownership_v2_enabled,
    normalize_ownership_path,
)

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan

# Paths like site/copy.md, `site/index.html`, ./foo/bar.ts
_PATH_RE = re.compile(
    r"(?:`|\"|')?"
    r"((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9.+-]+)"
    r"(?:`|\"|')?"
)


@dataclass(frozen=True)
class AppendOverlap:
    """One new node colliding with one live / ownership holder."""

    new_role: str
    new_run_id: str
    live_role: str
    live_run_id: str
    reason: str  # "role" | "deliverable" | "role+deliverable" | "sibling_artifact"


def has_incomplete_nodes(
    live_plan: RunPlan | None,
    *,
    completed_run_ids: set[str] | frozenset[str] | None = None,
) -> bool:
    """True when the live graph still has nodes not yet terminal."""
    if live_plan is None or not live_plan.nodes:
        return False
    done = set(completed_run_ids or ())
    return any(n.run_id not in done for n in live_plan.nodes)


def _norm_role(role: str) -> str:
    """Seat key: strip whitespace, lowercase."""
    return "".join((role or "").lower().split())


def roles_overlap(a: str, b: str) -> bool:
    """True when two roles claim the same seat (normalized name equality)."""
    na, nb = _norm_role(a), _norm_role(b)
    if not na or not nb:
        return False
    return na == nb


def apply_vacated_seat_replaces(
    new_plan: RunPlan,
    live_plan: RunPlan | None,
    *,
    completed_run_ids: set[str] | frozenset[str] | None = None,
    vacated_run_ids: set[str] | frozenset[str] | None = None,
) -> list[tuple[str, str]]:
    """Auto-fill ``replaces_run_id`` when a new node reclaims a vacated seat.

    Vacated = FAILED / CANCELLED / SKIPPED (caller supplies ``vacated_run_ids``).
    Requires exact seat match and no incomplete same-seat peer on the live graph.
    Explicit ``replaces_run_id`` / ``continue_from_run_id`` are left untouched.
    Mutates matching new nodes in place; returns ``(new_run_id, old_run_id)`` pairs.
    """
    if live_plan is None or not new_plan.nodes:
        return []
    vacated = {str(x).strip() for x in (vacated_run_ids or ()) if str(x).strip()}
    if not vacated:
        return []
    done = set(completed_run_ids or ())

    incomplete_seats: set[str] = set()
    vacated_by_seat: dict[str, list[Any]] = {}
    for live in live_plan.nodes:
        seat = _norm_role(_node_role(live))
        if not seat:
            continue
        if live.run_id not in done:
            incomplete_seats.add(seat)
        elif live.run_id in vacated:
            vacated_by_seat.setdefault(seat, []).append(live)

    applied: list[tuple[str, str]] = []
    for nn in new_plan.nodes:
        if (getattr(nn, "replaces_run_id", None) or "").strip():
            continue
        if (getattr(nn, "continue_from_run_id", None) or "").strip():
            continue
        seat = _norm_role(_node_role(nn))
        if not seat or seat in incomplete_seats:
            continue
        candidates = vacated_by_seat.get(seat) or []
        if not candidates:
            continue
        # Most recent vacated holder of this seat (plan order).
        old = candidates.pop()
        nn.replaces_run_id = old.run_id
        applied.append((nn.run_id, old.run_id))
        if not candidates:
            vacated_by_seat.pop(seat, None)
    return applied


def _normalize_path(path: str) -> str:
    """Align with WriteCoordinator keys (case-preserving)."""
    return normalize_ownership_path(path)


def _paths_in_text(text: str) -> set[str]:
    if not text:
        return set()
    return {_normalize_path(m.group(1)) for m in _PATH_RE.finditer(text)}


def node_artifact_paths(node: Any) -> set[str]:
    """Concrete ``deliverable.artifacts`` file paths (C3 declare / ownership keys).

    Directory prefixes, stage dirs, and globs are acceptance-only — excluded here.
    """
    from agentcore.runtime.runs.artifact_dir import is_file_ownership_path

    out: set[str] = set()
    deliverable = getattr(node, "deliverable", None)
    if deliverable is None:
        return out
    for art in getattr(deliverable, "artifacts", None) or []:
        if isinstance(art, str) and art.strip() and is_file_ownership_path(art):
            key = _normalize_path(art)
            if key:
                out.add(key)
    return out


def node_file_targets(node: Any) -> set[str]:
    """Declared artifact paths + paths mentioned in task / deliverable name."""
    out = set(node_artifact_paths(node))
    deliverable = getattr(node, "deliverable", None)
    if deliverable is not None:
        name = getattr(deliverable, "name", None)
        if isinstance(name, str):
            out |= _paths_in_text(name)
    out |= _paths_in_text(_node_task(node))
    return out


def _ancestors_for_plan(plan: RunPlan) -> dict[str, frozenset[str]]:
    from agentcore.runtime.runs.executor_context import _ancestors_by_id

    return _ancestors_by_id(plan)


def find_sibling_artifact_crosses(plan: RunPlan) -> list[AppendOverlap]:
    """Same-batch nodes declaring the same artifact without ancestor handoff."""
    if not plan.nodes:
        return []
    ancestors = _ancestors_for_plan(plan)
    by_path: dict[str, list[Any]] = {}
    for n in plan.nodes:
        for p in node_artifact_paths(n):
            by_path.setdefault(p, []).append(n)
    hits: list[AppendOverlap] = []
    seen_pairs: set[tuple[str, str]] = set()
    for _path, holders in by_path.items():
        if len(holders) < 2:
            continue
        for i, a in enumerate(holders):
            for b in holders[i + 1 :]:
                a_anc = ancestors.get(a.run_id, frozenset())
                b_anc = ancestors.get(b.run_id, frozenset())
                if a.run_id in b_anc or b.run_id in a_anc:
                    continue
                pair = tuple(sorted((a.run_id, b.run_id)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                hits.append(
                    AppendOverlap(
                        new_role=_node_role(b) or b.run_id,
                        new_run_id=b.run_id,
                        live_role=_node_role(a) or a.run_id,
                        live_run_id=a.run_id,
                        reason="sibling_artifact",
                    )
                )
    return hits


def find_append_overlaps(
    new_plan: RunPlan,
    live_plan: RunPlan | None,
    *,
    completed_run_ids: set[str] | frozenset[str] | None = None,
    ownership: WriteCoordinator | None = None,
) -> list[AppendOverlap]:
    """Return overlaps between ``new_plan`` nodes and live / ownership holders."""
    if not new_plan.nodes:
        return []

    # Same-batch sibling artifact crosses (C3 declare-time).
    hits: list[AppendOverlap] = []
    if file_ownership_v2_enabled():
        hits = find_sibling_artifact_crosses(new_plan)

    if live_plan is None:
        return hits

    done = set(completed_run_ids or ())
    incomplete = [n for n in live_plan.nodes if n.run_id not in done]
    live_by_id = {n.run_id: n for n in live_plan.nodes}
    v2 = file_ownership_v2_enabled() and ownership is not None

    # Legacy short-circuit: no incomplete → no role/file heuristic.
    if not v2 and not incomplete:
        return hits

    combined_ancestors = _ancestors_for_plan(live_plan)
    # New nodes may depend on live ids — fold their depends_on into ancestor sets.
    for nn in new_plan.nodes:
        deps = frozenset(getattr(nn, "depends_on", None) or ())
        extra = set(deps)
        for d in deps:
            extra |= set(combined_ancestors.get(d, frozenset()))
        combined_ancestors[nn.run_id] = frozenset(extra)

    for nn in new_plan.nodes:
        replaces = (getattr(nn, "replaces_run_id", None) or "").strip()
        continue_from = (getattr(nn, "continue_from_run_id", None) or "").strip()
        # Explicit replaces is plan surgery — skip overlap (transfer happens at declare).
        if replaces:
            continue
        n_role = _node_role(nn)
        n_files = node_artifact_paths(nn) if v2 else node_file_targets(nn)
        n_anc = set(combined_ancestors.get(nn.run_id, frozenset()))
        if continue_from:
            n_anc.add(continue_from)

        # --- Role overlaps: incomplete live nodes only (role gate retained) ---
        role_hit_live = None
        for live in incomplete:
            if roles_overlap(n_role, _node_role(live)):
                role_hit_live = live
                break

        # --- File overlaps ---
        file_hit_id: str | None = None
        file_hit_role = ""
        if v2 and n_files and ownership is not None:
            for path in n_files:
                owner = ownership.owner_of(path)
                if owner is None:
                    continue
                if owner == nn.run_id or owner in n_anc:
                    continue
                file_hit_id = owner
                live_node = live_by_id.get(owner)
                file_hit_role = (_node_role(live_node) if live_node else "") or owner
                break
        elif not v2 and incomplete:
            for live in incomplete:
                live_files = node_file_targets(live)
                if n_files and live_files and (n_files & live_files):
                    file_hit_id = live.run_id
                    file_hit_role = _node_role(live) or live.run_id
                    break

        if role_hit_live is None and file_hit_id is None:
            continue
        if role_hit_live is not None and file_hit_id is not None:
            role_id = role_hit_live.run_id
            if role_id == file_hit_id:
                hits.append(
                    AppendOverlap(
                        new_role=n_role or nn.run_id,
                        new_run_id=nn.run_id,
                        live_role=_node_role(role_hit_live) or role_hit_live.run_id,
                        live_run_id=role_id,
                        reason="role+deliverable",
                    )
                )
            else:
                # Different parties: report seat collision and file owner separately.
                hits.append(
                    AppendOverlap(
                        new_role=n_role or nn.run_id,
                        new_run_id=nn.run_id,
                        live_role=_node_role(role_hit_live) or role_hit_live.run_id,
                        live_run_id=role_id,
                        reason="role",
                    )
                )
                hits.append(
                    AppendOverlap(
                        new_role=n_role or nn.run_id,
                        new_run_id=nn.run_id,
                        live_role=file_hit_role,
                        live_run_id=file_hit_id or "",
                        reason="deliverable",
                    )
                )
        elif role_hit_live is not None:
            hits.append(
                AppendOverlap(
                    new_role=n_role or nn.run_id,
                    new_run_id=nn.run_id,
                    live_role=_node_role(role_hit_live) or role_hit_live.run_id,
                    live_run_id=role_hit_live.run_id,
                    reason="role",
                )
            )
        else:
            hits.append(
                AppendOverlap(
                    new_role=n_role or nn.run_id,
                    new_run_id=nn.run_id,
                    live_role=file_hit_role,
                    live_run_id=file_hit_id or "",
                    reason="deliverable",
                )
            )
    return hits


def append_overlap_reject_message(
    overlaps: list[AppendOverlap],
    *,
    completed: int,
    total: int,
) -> str:
    """Structured rejection body for the delegate tool result."""
    if not overlaps:
        return (
            "【队员追加已拒绝·座位重叠】当前协作图仍有未完成节点"
            f"（已完成 {completed}/{total}），本次追加与现有计划冲突。"
            "请等待波次推进，或用 cancel_worker / replan / replaces_run_id "
            "显式调整现有计划后再派。"
            "已完成/已交接节点不能靠 cancel_worker 撤销，须 replaces_run_id 接手补派。"
        )
    detail_parts: list[str] = []
    for o in overlaps:
        why = {
            "role": "座位（角色名）重叠",
            "deliverable": "交付物/文件归属重叠",
            "role+deliverable": "座位与文件归属均重叠",
            "sibling_artifact": f"同批交付物交叉（`{o.live_run_id}` 与 `{o.new_run_id}`）",
        }.get(o.reason, o.reason)
        if o.reason == "sibling_artifact":
            detail_parts.append(
                f"【{o.new_role}】与【{o.live_role}】{why}"
            )
        elif o.reason == "role":
            detail_parts.append(
                f"【{o.new_role}】与在图座位【{o.live_role}】（`{o.live_run_id}`）{why}"
            )
        elif o.reason == "deliverable":
            detail_parts.append(
                f"【{o.new_role}】与文件主人【{o.live_role}】（`{o.live_run_id}`）{why}"
            )
        else:
            detail_parts.append(
                f"【{o.new_role}】与在图【{o.live_role}】（`{o.live_run_id}`）{why}"
            )
    detail = "；".join(detail_parts)
    return (
        "【队员追加已拒绝·座位/交付物重叠】"
        f"（已完成 {completed}/{total}）。冲突：{detail}。"
        "请等待波次推进，或显式 cancel_worker / replan / replaces_run_id 接手后再追加；"
        "已完成/已交接节点不能靠 cancel_worker 撤销，须 replaces_run_id 接手补派；"
        "勿为「闲着」重复派与计划或已占文件重合的队员；"
        "不要另起同名终稿抢写——应改自己的文件或等整合。"
    )


def declare_plan_artifacts(
    plan: RunPlan,
    ownership: WriteCoordinator,
    *,
    force: bool = False,
    only_run_ids: set[str] | frozenset[str] | None = None,
    ancestor_map: dict[str, frozenset[str]] | None = None,
    ancestor_handoff_at_declare: bool = False,
    completed_run_ids: set[str] | frozenset[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Reserve deliverable.artifacts for each node; apply replaces/continue transfers.

    By default (``ancestor_handoff_at_declare=False``) a downstream node that lists the
    same path as an ancestor **does not** steal the lock at dispatch — the ancestor
    keeps holding until write-time claim, completion handoff, or explicit transfer.
    Nested lead→child drives pass ``ancestor_handoff_at_declare=True``.

    When ``completed_run_ids`` is set, a hard conflict against a **completed** holder is
    treated as dispatch-time handoff (审校→修订跨波次)：新节点声明同路径即接手，无需
    用户点「移交写权」。仍在跑的锁主 / 未完成占位保持冲突。

    Returns list of ``(new_run_id, path, conflicting_owner)`` for hard conflicts
    when not force/transfer-eligible (caller should have rejected via overlaps first).
    """
    ancestors = ancestor_map if ancestor_map is not None else _ancestors_for_plan(plan)
    # Topological-ish: nodes with fewer deps first so ancestors register before intent.
    ordered = sorted(plan.nodes, key=lambda n: len(getattr(n, "depends_on", None) or ()))
    conflicts: list[tuple[str, str, str]] = []
    only = set(only_run_ids) if only_run_ids is not None else None
    done = {str(x).strip() for x in (completed_run_ids or ()) if str(x).strip()}
    dispatch_handoffs: list[tuple[str, str, str]] = []

    for node in ordered:
        rid = node.run_id
        if only is not None and rid not in only:
            continue
        replaces = (getattr(node, "replaces_run_id", None) or "").strip()
        continue_from = (getattr(node, "continue_from_run_id", None) or "").strip()
        if replaces:
            ownership.transfer_all_from(replaces, rid)
        if continue_from:
            # Same-author continuation: paths still held by the continued run move over.
            ownership.transfer_all_from(continue_from, rid)

        anc = set(ancestors.get(rid, frozenset()))
        if continue_from:
            anc.add(continue_from)
        if replaces:
            anc.add(replaces)
        anc_f = frozenset(anc)

        for path in node_artifact_paths(node):
            if force or replaces or continue_from:
                ownership.transfer(path, rid)
                continue
            owner = ownership.declare(
                path,
                rid,
                anc_f,
                force=False,
                allow_ancestor_handoff=ancestor_handoff_at_declare,
            )
            if owner is not None:
                if owner in done:
                    # 原主已完成、本协作会话内仍占位 → 新波次声明同 artifact 即接手。
                    ownership.transfer(path, rid)
                    dispatch_handoffs.append((path, owner, rid))
                    continue
                conflicts.append((rid, path, owner))
    if dispatch_handoffs:
        try:
            from agentcore.core.logging import get_logger

            get_logger(__name__).info(
                "file_ownership.dispatch_handoff",
                transfers=[
                    {"path": path, "from": old, "to": new}
                    for path, old, new in dispatch_handoffs
                ],
            )
        except Exception:  # noqa: BLE001 — never break dispatch
            pass
    return conflicts


def handoff_owned_paths_on_complete(
    plan: RunPlan,
    ownership: WriteCoordinator,
    completed_run_id: str,
    *,
    completed_run_ids: set[str] | frozenset[str] | None = None,
    ancestor_map: dict[str, frozenset[str]] | None = None,
) -> list[tuple[str, str]]:
    """Move completed worker's paths to the unique unfinished dependent listing them.

    Returns ``(path, new_owner_run_id)`` pairs actually transferred. Ambiguous
    (0 or 2+ candidates) paths stay with the completed owner for write-time claim
    or explicit ``transfer_ownership``.
    """
    rid = (completed_run_id or "").strip()
    if not rid or not plan.nodes:
        return []
    owned = ownership.owned_paths(rid)
    if not owned:
        return []
    ancestors = ancestor_map if ancestor_map is not None else _ancestors_for_plan(plan)
    done = set(completed_run_ids or ())
    done.add(rid)
    moved: list[tuple[str, str]] = []
    for path in owned:
        candidates: list[str] = []
        direct: list[str] = []
        for node in plan.nodes:
            nid = (getattr(node, "run_id", None) or "").strip()
            if not nid or nid == rid or nid in done:
                continue
            if path not in node_artifact_paths(node):
                continue
            anc = ancestors.get(nid, frozenset())
            if rid not in anc:
                continue
            candidates.append(nid)
            deps = set(getattr(node, "depends_on", None) or ())
            if rid in deps:
                direct.append(nid)
        pool = direct if len(direct) == 1 else (candidates if len(candidates) == 1 else [])
        if len(pool) != 1:
            continue
        new_owner = pool[0]
        ownership.transfer(path, new_owner)
        moved.append((path, new_owner))
    return moved


def declare_nested_drive_artifacts(
    tool: Any,
    plan: RunPlan,
    *,
    execution_id: str,
) -> list[tuple[str, str, str]]:
    """Path-level ownership handoff for nested (depth≥1) blocking drives.

    Nested sub-teams share the parent coordination ledger via
    :func:`~agentcore.workspace.write_claims.resolve_write_coordinator` but never
    enter :func:`try_start_coordination`, so they previously skipped dispatch-time
    declare. With ``parent_run_id`` in the ancestor map, declaring the child's
    artifacts transfers only those paths from the lead (not ``transfer_all_from``).
    Root depth-0 coordination already declares in ``host`` — skipped here.
    """
    from agentcore.workspace.write_claims import (
        file_ownership_v2_enabled,
        resolve_write_coordinator,
    )

    if not file_ownership_v2_enabled():
        return []
    if int(getattr(tool, "_depth", 0) or 0) < 1:
        return []

    ownership = resolve_write_coordinator(execution_id=execution_id)
    force = bool(getattr(tool, "_delegate_force", False))
    completed: set[str] | frozenset[str] | None = None
    try:
        from agentcore.runtime.coordination.session import active_coordination

        sess = active_coordination(execution_id)
        if sess is not None:
            completed = sess.completed_run_ids
    except Exception:  # noqa: BLE001
        completed = None
    conflicts = declare_plan_artifacts(
        plan,
        ownership,
        force=force,
        ancestor_map=_ancestors_for_plan(plan),
        ancestor_handoff_at_declare=True,
        completed_run_ids=completed,
    )
    if conflicts:
        from agentcore.core.logging import get_logger

        get_logger(__name__).info(
            "coordination.nested_declare_conflicts",
            execution_id=execution_id,
            depth=int(getattr(tool, "_depth", 0) or 0),
            conflicts=[
                {"run_id": rid, "path": path, "owner": owner}
                for rid, path, owner in conflicts
            ],
        )
    return conflicts
