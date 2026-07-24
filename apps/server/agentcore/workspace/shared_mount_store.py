"""In-process session registry for shared-space mounts (cloud second root).

Keyed by conversation_id → alias → SharedMount. Session-scoped like W3 external
grants: cleared on revoke / conversation delete / account cleanup. Membership
changes are enforced by the realtime gate on each file op, not by this store.
"""

from __future__ import annotations

import threading

from agentcore.workspace.shared_mounts import (
    SharedMount,
    SharedMountMode,
    sanitize_alias,
    uniquify_alias,
)

_lock = threading.Lock()
_mounts: dict[str, dict[str, SharedMount]] = {}


def list_mounts(conversation_id: str) -> list[SharedMount]:
    with _lock:
        return list(_mounts.get(conversation_id, {}).values())


def mounts_as_dict(conversation_id: str) -> dict[str, SharedMount]:
    with _lock:
        return dict(_mounts.get(conversation_id, {}))


def add_mount(
    conversation_id: str,
    *,
    space_id: str,
    label: str,
    mode: SharedMountMode,
    alias_hint: str | None = None,
) -> SharedMount:
    """Register or refresh a shared mount. Same ``space_id`` keeps the alias."""
    with _lock:
        by_alias = _mounts.setdefault(conversation_id, {})
        for existing in by_alias.values():
            if existing.space_id == space_id:
                updated = SharedMount(
                    alias=existing.alias,
                    space_id=space_id,
                    label=label or existing.label,
                    mode=mode,
                )
                by_alias[existing.alias] = updated
                return updated
        taken = set(by_alias)
        alias = uniquify_alias(alias_hint or label or sanitize_alias(space_id), taken)
        mount = SharedMount(
            alias=alias,
            space_id=space_id,
            label=label or alias,
            mode=mode,
        )
        by_alias[alias] = mount
        return mount


def revoke_mount(
    conversation_id: str,
    *,
    alias: str | None = None,
    space_id: str | None = None,
) -> bool:
    with _lock:
        by_alias = _mounts.get(conversation_id)
        if not by_alias:
            return False
        if alias is None and space_id is None:
            del _mounts[conversation_id]
            return True
        removed = False
        if alias and alias in by_alias:
            del by_alias[alias]
            removed = True
        if space_id:
            for a, m in list(by_alias.items()):
                if m.space_id == space_id:
                    del by_alias[a]
                    removed = True
        if not by_alias:
            _mounts.pop(conversation_id, None)
        return removed


def clear_conversation(conversation_id: str) -> None:
    with _lock:
        _mounts.pop(conversation_id, None)


def revoke_space_everywhere(space_id: str) -> None:
    """Drop mounts of a deleted / inaccessible space from every conversation."""
    with _lock:
        empty: list[str] = []
        for cid, by_alias in _mounts.items():
            for a, m in list(by_alias.items()):
                if m.space_id == space_id:
                    del by_alias[a]
            if not by_alias:
                empty.append(cid)
        for cid in empty:
            _mounts.pop(cid, None)


def revoke_user_everywhere(user_id: str, conversation_ids: list[str]) -> None:
    """Clear shared mounts for conversations owned by a leaving member."""
    with _lock:
        for cid in conversation_ids:
            _mounts.pop(cid, None)


def clear_all_for_tests() -> None:
    with _lock:
        _mounts.clear()
