"""File ownership ledger (C3 · 较强文件归属).

Two eras share one class:

* **Legacy (``engine_file_ownership_v2=False``)** — per-batch ``WriteCoordinator``:
  first successful ``file_write`` / ``file_append`` claims the path; concurrent
  unrelated siblings are refused; cross-batch overwrite is intentionally open.
* **C3 (default on)** — one ledger per coordination ``execution_id`` (session
  authority, snapshotted). Artifacts are reserved at dispatch; completed owners
  still hold paths until session end or explicit transfer
  (``replaces_run_id`` / ``continue_from_run_id`` / ``force`` / ancestor handoff).
  Write tools consult the same book (``str_replace`` / ``write_section`` /
  delete / move included). Non-coordination batches still get a batch-local
  ledger for intra-batch mutual exclusion.

``code_execute`` workspace write-back is **not** hard-gated this period — only
observable; do not route it through :meth:`claim` without an explicit follow-up.

→ 见设计: docs/03-AI核心/编排器与CEO主Agent.md §2.3
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
) -> str:
    """Guiding refusal: name the owner; do **not** push renaming the final deliverable."""
    who = f"【{owner_role}】（`{owner_run_id}`）" if owner_role else f"`{owner_run_id}`"
    return (
        f"写入冲突：`{path}` 已归队友 {who} 负责。"
        "请改写你自己职责下的文件，或等待其整合完成；"
        "若需接手该终稿，请由主管用 replaces_run_id / replan / force 显式移交，"
        "不要另起同名终稿文件名抢写。"
    )


class WriteCoordinator:
    """Owning run_id per normalized path (batch-local or session-shared).

    Holds no async state and no lock — every method is synchronous, relying on the
    single-threaded event loop for atomicity (claim/declare before the awaited write).
    """

    def __init__(self, owners: dict[str, str] | None = None) -> None:
        # normalized path -> run_id
        self._owner: dict[str, str] = {
            _normalize(p): rid for p, rid in (owners or {}).items() if _normalize(p) and rid
        }

    def to_dict(self) -> dict[str, str]:
        return dict(self._owner)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WriteCoordinator:
        if not data or not isinstance(data, dict):
            return cls()
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
        """Try to record ``run_id`` as the writer of ``path``.

        Returns ``None`` when the write may proceed — unclaimed, already owned by
        ``run_id``, owned by an ancestor (handoff), or ``force`` — and records
        ownership. Returns the conflicting owner's run_id (leaving ownership
        untouched unless ``force``) when an unrelated peer already holds it.
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
    ) -> str | None:
        """Dispatch-time reserve (same rules as :meth:`claim`)."""
        return self.claim(path, run_id, ancestors, force=force)

    def transfer(self, path: str, new_owner: str) -> None:
        """Force path → ``new_owner`` (replaces / continue_from / force handoff)."""
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
