"""File ownership ledger (C3 · 较强文件归属 / 交接式写权).

Two eras share one class:

* **Legacy (``engine_file_ownership_v2=False``)** — per-batch ``WriteCoordinator``:
  first successful ``file_write`` / ``file_append`` claims the path; concurrent
  unrelated siblings are refused; cross-batch overwrite is intentionally open.
* **C3 (default on)** — one ledger per coordination ``execution_id`` (session
  authority, snapshotted). **交接式写权**：

  - **Dispatch ``declare``** claims a free path; does **not** steal from an
    ancestor holder (downstream only records intent via plan artifacts). Nested
    lead→child drives opt into declare-time handoff explicitly.
  - **Write ``claim``** may hand off from an ancestor (downstream consolidates).
  - **Completion handoff** moves owned paths to the unique dependent that listed
    the same artifact.
  - Explicit transfer: ``replaces_run_id`` / ``continue_from_run_id`` / ``force`` /
    ``resolve_escalation(transfer_ownership=true)`` / user structured裁决.

  Write tools consult the same book (``str_replace`` / ``write_section`` /
  delete / move included). Write ancestors = plan ``depends_on`` closure ∪
  nested ``parent_run_id``. Non-coordination batches still get a batch-local
  ledger for intra-batch mutual exclusion.

``code_execute`` workspace write-back is **not** hard-gated this period — only
observable; do not route it through :meth:`claim` without an explicit follow-up.

→ 见设计: docs/03-AI核心/Agent协作模式.md §三
"""

from __future__ import annotations

from posixpath import normpath
from typing import Any


def _normalize(path: str) -> str:
    """Canonical key for a workspace-relative path so ``a/b``, ``./a/b`` and ``a//b``
    collide on one owner. POSIX separators, collapsed, leading slashes stripped; case
    is preserved (the server filesystem is case-sensitive). ``..`` traversal is left to
    the backend's own guard — this only needs a stable key, not a safe path."""
    return normpath((path or "").strip().replace("\\", "/")).lstrip("/")


def normalize_ownership_path(path: str) -> str:
    """Public alias for dispatch / append-guard path keys (same as claim keys)."""
    return _normalize(path)


def file_ownership_v2_enabled() -> bool:
    """C3 stronger ownership. ``False`` rolls back to incomplete-heuristic + batch write/append."""
    try:
        from agentcore.config import settings

        return bool(getattr(settings, "engine_file_ownership_v2", True))
    except Exception:  # noqa: BLE001 — settings optional in unit stubs
        return True


def ownership_conflict_message(
    path: str,
    owner_run_id: str,
    *,
    owner_role: str | None = None,
    ownership_kind: str | None = None,
    owner_status: str | None = None,
) -> str:
    """Guiding refusal: name the owner; do **not** push renaming the final deliverable.

    ``ownership_kind``: ``\"declared\"`` (dispatch reserve, file may be empty/missing) or
    ``\"written\"`` (successful write recorded). ``owner_status``: ``running`` /
    ``completed`` / ``unknown``.
    """
    who = f"【{owner_role}】（`{owner_run_id}`）" if owner_role else f"`{owner_run_id}`"
    kind_bit = ""
    if ownership_kind == "declared":
        kind_bit = "（仅派发占位、尚未落盘——不是上一 run 残留锁）"
    elif ownership_kind == "written":
        kind_bit = "（锁主已成功写入过该路径）"
    status_bit = ""
    if owner_status == "running":
        status_bit = "锁主状态：进行中。"
    elif owner_status == "completed":
        status_bit = "锁主状态：已完成（本协作会话内仍占位）。"
    elif owner_status == "unknown":
        status_bit = "锁主状态：未知（批内账本或无协调会话）。"
    return (
        f"写入冲突：`{path}` 已归队友 {who} 负责{kind_bit}。"
        f"{status_bit}"
        "请改写你自己职责下的文件，或等待其整合完成；"
        "若需接手该路径：escalate 后用户卡可点「移交写权」，或由主管 "
        "resolve_escalation(..., transfer_ownership=true, paths=[本路径])；"
        "不要另起同名终稿文件名抢写。"
    )


class WriteCoordinator:
    """Owning run_id per normalized path (batch-local or session-shared).

    Holds no async state and no lock — every method is synchronous, relying on the
    single-threaded event loop for atomicity (claim/declare before the awaited write).
    """

    def __init__(
        self,
        owners: dict[str, str] | None = None,
        *,
        written: set[str] | frozenset[str] | None = None,
    ) -> None:
        # normalized path -> run_id
        self._owner: dict[str, str] = {
            _normalize(p): rid for p, rid in (owners or {}).items() if _normalize(p) and rid
        }
        # Paths that saw a successful write/append/edit under the ledger (not declare-only).
        self._written: set[str] = {
            _normalize(p) for p in (written or ()) if _normalize(p)
        }

    def to_dict(self) -> dict[str, Any]:
        """Snapshot: v2 nested ``{owners, written}``; empty written may still use v2."""
        return {
            "_v": 2,
            "owners": dict(self._owner),
            "written": sorted(self._written),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WriteCoordinator:
        if not data or not isinstance(data, dict):
            return cls()
        if data.get("_v") == 2 or isinstance(data.get("owners"), dict):
            raw_owners = data.get("owners") or {}
            owners = {
                str(k): str(v)
                for k, v in raw_owners.items()
                if isinstance(k, str) and v is not None and str(v).strip()
            }
            raw_written = data.get("written") or []
            written = {
                str(p)
                for p in raw_written
                if isinstance(p, str) and str(p).strip()
            }
            return cls(owners, written=written)
        # Legacy flat path → owner.
        owners = {
            str(k): str(v)
            for k, v in data.items()
            if isinstance(k, str) and v is not None and str(v).strip()
        }
        return cls(owners)

    def owner_of(self, path: str) -> str | None:
        key = _normalize(path)
        if not key:
            return None
        return self._owner.get(key)

    def is_written(self, path: str) -> bool:
        key = _normalize(path)
        return bool(key) and key in self._written

    def mark_written(self, path: str) -> None:
        key = _normalize(path)
        if key:
            self._written.add(key)

    def owned_paths(self, run_id: str) -> list[str]:
        rid = (run_id or "").strip()
        if not rid:
            return []
        return sorted(p for p, owner in self._owner.items() if owner == rid)

    def claim(
        self,
        path: str,
        run_id: str,
        ancestors: frozenset[str],
        *,
        force: bool = False,
    ) -> str | None:
        """Try to record ``run_id`` as the writer of ``path`` (write-time).

        Returns ``None`` when the write may proceed — unclaimed, already owned by
        ``run_id``, owned by an ancestor (write-time handoff), or ``force`` — and
        records ownership. Returns the conflicting owner's run_id (leaving
        ownership untouched unless ``force``) when an unrelated peer already holds it.
        """
        key = _normalize(path)
        if not key:
            return None
        rid = (run_id or "").strip() or "unknown"
        owner = self._owner.get(key)
        if owner is not None and owner != rid and owner not in ancestors and not force:
            return owner
        self._owner[key] = rid
        return None

    def declare(
        self,
        path: str,
        run_id: str,
        ancestors: frozenset[str],
        *,
        force: bool = False,
        allow_ancestor_handoff: bool = False,
    ) -> str | None:
        """Dispatch-time reserve — does **not** steal from an ancestor by default.

        Free path → become holder. Same run → ok. Ancestor already holds → keep
        ancestor (downstream intent only) unless ``allow_ancestor_handoff`` (nested
        lead→child declare) or ``force``. Unrelated holder → return conflict owner.
        """
        key = _normalize(path)
        if not key:
            return None
        rid = (run_id or "").strip() or "unknown"
        owner = self._owner.get(key)
        if owner is None or owner == rid or force:
            self._owner[key] = rid
            return None
        if owner in ancestors:
            if allow_ancestor_handoff:
                self._owner[key] = rid
            return None
        return owner

    def transfer(self, path: str, new_owner: str) -> None:
        """Force path → ``new_owner`` (replaces / continue_from / force handoff).

        Written-bit stays with the path (content may already exist on disk).
        """
        key = _normalize(path)
        rid = (new_owner or "").strip()
        if not key or not rid:
            return
        self._owner[key] = rid

    def transfer_all_from(self, old_owner: str, new_owner: str) -> list[str]:
        """Move every path owned by ``old_owner`` to ``new_owner``. Returns moved paths."""
        old = (old_owner or "").strip()
        new = (new_owner or "").strip()
        if not old or not new or old == new:
            return []
        moved: list[str] = []
        for path, owner in list(self._owner.items()):
            if owner == old:
                self._owner[path] = new
                moved.append(path)
        return moved

    def release(self, path: str, run_id: str) -> None:
        """Drop ``run_id``'s ownership of ``path`` (only if it still holds it).

        Called when a claimed write then FAILS, so a path the run never actually created
        doesn't spuriously block a sibling. Does **not** release dispatch-time declares
        that were never followed by a failed write of a brand-new path — callers only
        release after a claim that preceded a failed I/O.
        """
        key = _normalize(path)
        if self._owner.get(key) == run_id:
            del self._owner[key]
            self._written.discard(key)


def resolve_write_coordinator(
    *,
    execution_id: str | None = None,
    fallback: WriteCoordinator | None = None,
) -> WriteCoordinator:
    """Session ledger when C3 + coordination is live; else ``fallback`` or a fresh batch book.

    Nested sub-teams share the parent coordination session via
    :data:`current_execution_id` when their own ``execution_id`` has no session.
    """
    if not file_ownership_v2_enabled():
        return fallback if fallback is not None else WriteCoordinator()

    from agentcore.runtime.coordination.session import (
        active_coordination,
        current_execution_id,
    )

    eid = (execution_id or "").strip()
    session = active_coordination(eid) if eid else None
    if session is None:
        parent_eid = (current_execution_id.get() or "").strip()
        if parent_eid and parent_eid != eid:
            session = active_coordination(parent_eid)
    if session is not None:
        return session.ensure_file_ownership()
    if fallback is not None:
        return fallback
    return WriteCoordinator()


def lookup_owner_status(
    owner_run_id: str,
    *,
    execution_id: str | None = None,
) -> tuple[str | None, str]:
    """Return ``(owner_role | None, owner_status)`` from the active coordination session.

    ``owner_status`` is ``running`` / ``completed`` / ``unknown``.
    """
    rid = (owner_run_id or "").strip()
    if not rid:
        return None, "unknown"
    try:
        from agentcore.runtime.coordination.session import active_coordination

        session = active_coordination(execution_id)
    except Exception:  # noqa: BLE001
        return None, "unknown"
    if session is None:
        return None, "unknown"

    role: str | None = None
    running = dict(session.running_workers())
    if rid in running:
        status = "running"
        label = (running.get(rid) or "").strip()
        role = label if label and label != rid else None
    elif rid in session.completed_run_ids:
        status = "completed"
    else:
        status = "unknown"

    plan = getattr(session, "live_plan", None)
    if plan is not None and hasattr(plan, "by_id"):
        node = plan.by_id(rid)
        if node is not None:
            node_role = (getattr(node, "role", None) or "").strip()
            if node_role:
                role = role or node_role
    return role, status


def parse_ownership_conflict_paths(text: str) -> list[str]:
    """Extract paths from ownership-conflict tool errors embedded in escalate questions."""
    import re

    return list(
        dict.fromkeys(
            m.group(1).strip()
            for m in re.finditer(r"写入冲突：`([^`]+)`", text or "")
            if m.group(1) and m.group(1).strip()
        )
    )


def ownership_escalation_hints(
    *,
    escalator_run_id: str,
    question: str = "",
    execution_id: str | None = None,
    paths: list[str] | None = None,
    write_ancestors: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Structured ownership hints for CEO escalation inject / resolve transfer.

    Returns keys: ownership_paths, lock_owner_run_id, escalator_is_lock_owner_nested_child,
    ownership_kind, owner_status (empty dict when no conflict path resolved).
    """
    hints: dict[str, Any] = {}
    path_list = [p for p in (paths or []) if isinstance(p, str) and p.strip()]
    if not path_list:
        path_list = parse_ownership_conflict_paths(question)
    if not path_list:
        return hints

    ledger = resolve_write_coordinator(execution_id=execution_id)
    lock_owners: list[str] = []
    kinds: list[str] = []
    for p in path_list:
        owner = ledger.owner_of(p)
        if owner:
            lock_owners.append(owner)
            kinds.append("written" if ledger.is_written(p) else "declared")

    hints["ownership_paths"] = path_list
    if not lock_owners:
        return hints

    lock_owner = lock_owners[0]
    hints["lock_owner_run_id"] = lock_owner
    hints["ownership_kind"] = kinds[0] if kinds else None
    _role, status = lookup_owner_status(lock_owner, execution_id=execution_id)
    hints["owner_status"] = status
    anc = write_ancestors or frozenset()
    nested = lock_owner in anc or _is_nested_child_of(
        escalator_run_id, lock_owner, execution_id=execution_id
    )
    hints["escalator_is_lock_owner_nested_child"] = bool(nested)
    return hints


def _is_nested_child_of(
    child_run_id: str,
    parent_run_id: str,
    *,
    execution_id: str | None = None,
) -> bool:
    child = (child_run_id or "").strip()
    parent = (parent_run_id or "").strip()
    if not child or not parent or child == parent:
        return False
    try:
        from agentcore.runtime.coordination.session import active_coordination

        session = active_coordination(execution_id)
    except Exception:  # noqa: BLE001
        return False
    if session is None:
        return False
    plan = getattr(session, "live_plan", None)
    if plan is None or not hasattr(plan, "by_id"):
        return False
    node = plan.by_id(child)
    if node is None:
        for n in getattr(plan, "nodes", ()) or ():
            if getattr(n, "run_id", None) == child:
                node = n
                break
    if node is None:
        return False
    return (getattr(node, "parent_run_id", None) or "").strip() == parent
