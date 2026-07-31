"""In-workspace soft-delete zone for backends without an OS recycle bin.

Used by ``ServerWorkspace`` (cloud + sidecar): default ``delete`` moves the
target under ``AgentCore/trash/<id>/`` and writes ``meta.json`` with the
original relative path so a future restore can put it back. Local Electron
channels prefer ``shell.trashItem`` instead; this module is the no-trash fallback.

Internal zones (``AgentCore/{index,trash,baselines}``) are path-aware system
noise — trash entries never appear in agent listings / indexes. Hard-delete
bypass applies only to those zones, **not** the whole ``AgentCore/`` tree
(deleting rules/memory/docs must remain soft-deletable).
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from agentcore.core.types import new_id
from agentcore.workspace._paths import is_internal_zone_relpath
from agentcore.workspace.protocol import WorkspaceIOError
from agentcore.workspace.stage_dirs import TRASH_REL

_META_NAME = "meta.json"
_CONTENT_NAME = "content"


def is_internal_zone_path(rel_path: str) -> bool:
    """True when ``rel_path`` is an AgentCore internal zone or under one.

    Alias kept for call-site clarity (hard-delete bypass). Does **not** match
    bare ``AgentCore/`` or ``AgentCore/规则|记忆|文档``.
    """
    return is_internal_zone_relpath(rel_path)


# Backward-compatible name used by older call sites / tests.
is_trash_or_agentcore_path = is_internal_zone_path


def soft_delete_to_trash(*, root: Path, target: Path, original_rel: str) -> str:
    """Move ``target`` into the workspace trash zone; return the trash entry id.

    Layout::

        AgentCore/trash/<id>/
          meta.json   # original_path, deleted_at, is_dir, name
          content     # file, or directory tree

    Raises ``WorkspaceIOError`` on I/O failure.
    """
    trash_root = root / Path(*TRASH_REL.split("/"))
    entry_id = new_id()
    entry_dir = trash_root / entry_id
    try:
        entry_dir.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        raise WorkspaceIOError(str(e)) from e

    dest = entry_dir / _CONTENT_NAME
    is_dir = target.is_dir()
    try:
        shutil.move(str(target), str(dest))
    except OSError as e:
        shutil.rmtree(entry_dir, ignore_errors=True)
        raise WorkspaceIOError(str(e)) from e

    meta = {
        "original_path": original_rel.replace("\\", "/"),
        "deleted_at": datetime.now(UTC).isoformat(),
        "is_dir": is_dir,
        "name": target.name,
    }
    try:
        (entry_dir / _META_NAME).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        # Payload already under trash; leave it rather than risk a second move.
        raise WorkspaceIOError(str(e)) from e
    return entry_id
