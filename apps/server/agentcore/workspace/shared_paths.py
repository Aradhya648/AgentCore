"""On-disk path helpers for shared spaces (no ServerWorkspace import).

Kept separate from ``locate`` / ``server`` to avoid a circular import: both need
the shared-space root path, and ``locate`` already constructs ``ServerWorkspace``.
"""

from __future__ import annotations

from pathlib import Path

from agentcore.config import settings

_WORKSPACES_SEGMENT = "workspaces"
_SHARED_SEGMENT = "shared"


def shared_workspace_root_path(space_id: str) -> Path:
    """On-disk root for a shared space — without creating it."""
    return Path(settings.data_dir) / _WORKSPACES_SEGMENT / _SHARED_SEGMENT / space_id


def shared_workspace_has_entries(space_id: str) -> bool:
    root = shared_workspace_root_path(space_id)
    return root.is_dir() and any(root.iterdir())


def shared_workspace_storage_key(space_id: str) -> str:
    """Lock / snapshot key for a shared space (cross-user)."""
    return f"{_WORKSPACES_SEGMENT}/{_SHARED_SEGMENT}/{space_id}"


def resolve_shared_workspace_root(space_id: str) -> Path:
    root = shared_workspace_root_path(space_id)
    root.mkdir(parents=True, exist_ok=True)
    return root
