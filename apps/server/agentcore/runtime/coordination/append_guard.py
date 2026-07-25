"""Mid-coordination append overlap guard + C3 dispatch ownership.

When the live graph still has incomplete nodes, a secondary ``delegate`` that
overlaps an existing node in **role duty** is rejected (GEO collision class).

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
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from agentcore.runtime.coordination.isomorphic import _node_role, _node_task
from agentcore.workspace.write_claims import (
    WriteCoordinator,
    file_ownership_v2_enabled,
    normalize_ownership_path,
)

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan

# Role-stem similarity after stripping generic job suffixes.
_ROLE_SIMILARITY = 0.55
# Shared CJK/latin prefix length that counts as the same duty family (内容…).
_ROLE_PREFIX_MIN = 2

_GENERIC_ROLE_SUFFIXES = (
    "工程师",
    "专员",
    "助手",
    "分析师",
    "优化师",
    "编辑",
    "审校员",
    "研究员",
    "写手",
)

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
    return "".join((role or "").lower().split())


def _role_stem(role: str) -> str:
    """Strip generic job suffixes so 前端工程师 vs 测试工程师 do not false-match."""
    r = _norm_role(role)
    for suffix in _GENERIC_ROLE_SUFFIXES:
        s = suffix.lower()
        if r.endswith(s) and len(r) > len(s):
            return r[: -len(s)]
    return r


def roles_overlap(a: str, b: str) -> bool:
    """True when two role labels describe the same (or nested) duty family."""
    na, nb = _norm_role(a), _norm_role(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    sa, sb = _role_stem(a), _role_stem(b)
    if not sa or not sb:
        return False
    if sa == sb or sa in sb or sb in sa:
        return True
    if (
        len(sa) >= _ROLE_PREFIX_MIN
        and len(sb) >= _ROLE_PREFIX_MIN
        and sa[:_ROLE_PREFIX_MIN] == sb[:_ROLE_PREFIX_MIN]
    ):
        # Shared duty prefix (内容策略 / 内容文案) — not a bare generic suffix.
        return True
    return SequenceMatcher(None, sa, sb).ratio() >= _ROLE_SIMILARITY


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
            reason = "role+deliverable"
            live_role = _node_role(role_hit_live) or role_hit_live.run_id
            live_run_id = role_hit_live.run_id
        elif role_hit_live is not None:
            reason = "role"
            live_role = _node_role(role_hit_live) or role_hit_live.run_id
            live_run_id = role_hit_live.run_id
        else:
            reason = "deliverable"
            live_role = file_hit_role
            live_run_id = file_hit_id or ""
        hits.append(
            AppendOverlap(
                new_role=n_role or nn.run_id,
                new_run_id=nn.run_id,
                live_role=live_role,
                live_run_id=live_run_id,
                reason=reason,
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
            "【队员追加已拒绝·职责重叠】当前协作图仍有未完成节点"
            f"（已完成 {completed}/{total}），本次追加与现有计划冲突。"
            "请等待波次推进，或用 cancel_worker / replan 显式调整现有计划后再派。"
        )
    detail_parts: list[str] = []
    for o in overlaps:
        why = {
            "role": "角色职责重叠",
            "deliverable": "交付物/文件归属重叠",
            "role+deliverable": "角色职责与文件归属均重叠",
            "sibling_artifact": f"同批交付物交叉（`{o.live_run_id}` 与 `{o.new_run_id}`）",
        }.get(o.reason, o.reason)
        if o.reason == "sibling_artifact":
            detail_parts.append(
                f"【{o.new_role}】与【{o.live_role}】{why}"
            )
        else:
            detail_parts.append(
                f"【{o.new_role}】与在图【{o.live_role}】（`{o.live_run_id}`）{why}"
            )
    detail = "；".join(detail_parts)
    return (
        "【队员追加已拒绝·职责/交付物重叠】"
        f"（已完成 {completed}/{total}）。冲突：{detail}。"
        "请等待波次推进，或显式 cancel_worker / replan / replaces_run_id 接手后再追加；"
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
) -> list[tuple[str, str, str]]:
    """Reserve deliverable.artifacts for each node; apply replaces/continue transfers.

    Returns list of ``(new_run_id, path, conflicting_owner)`` for hard conflicts
    when not force/transfer-eligible (caller should have rejected via overlaps first).
    """
    ancestors = ancestor_map if ancestor_map is not None else _ancestors_for_plan(plan)
    # Topological-ish: nodes with fewer deps first so ancestors register before handoff.
    ordered = sorted(plan.nodes, key=lambda n: len(getattr(n, "depends_on", None) or ()))
    conflicts: list[tuple[str, str, str]] = []
    only = set(only_run_ids) if only_run_ids is not None else None

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
            owner = ownership.declare(path, rid, anc_f, force=False)
            if owner is not None:
                conflicts.append((rid, path, owner))
    return conflicts
