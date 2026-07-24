"""A1+ turn file diff — baseline snapshot vs live workspace (read-only).

复用 ``handoff_diff.diff_archives`` / ``FileChange``；另附 ``base_content`` 方便
桌面 ``lineDiff``。不做 apply。无基线 → ``available=False``。

Cloud: OSS/FS snapshot vs ``resolve_workspace_root``.
Local (sidecar): ``.agentcore/baselines/{id}.zip`` vs live workspace root.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from agentcore.storage._archive import unzip_into, zip_dir
from agentcore.workspace.handoff_diff import (
    FileChange,
    _decode_text,
    diff_archives,
    read_archive_entries,
)
from agentcore.workspace.locate import resolve_workspace_root
from agentcore.workspace.snapshots import read_snapshot
from agentcore.workspace.turn_baseline import local_baseline_path


@dataclass(frozen=True)
class TurnFileChange:
    """``FileChange`` + optional baseline UTF-8 text for modified/deleted preview."""

    path: str
    change_type: str
    base_sha: str | None
    result_sha: str | None
    is_binary: bool
    content: str | None
    size_bytes: int
    base_content: str | None


@dataclass(frozen=True)
class TurnFilesDiff:
    message_id: str
    baseline_snapshot_id: str | None
    available: bool
    changes: list[TurnFileChange]


def _enrich(
    changes: list[FileChange], base_entries: dict[str, bytes]
) -> list[TurnFileChange]:
    out: list[TurnFileChange] = []
    for c in changes:
        base_bytes = base_entries.get(c.path)
        base_text = _decode_text(base_bytes) if base_bytes is not None else None
        out.append(
            TurnFileChange(
                path=c.path,
                change_type=c.change_type,
                base_sha=c.base_sha,
                result_sha=c.result_sha,
                is_binary=c.is_binary,
                content=c.content,
                size_bytes=c.size_bytes,
                base_content=base_text,
            )
        )
    return out


def _diff_archives_enriched(base_archive: bytes, live_archive: bytes) -> list[TurnFileChange]:
    raw = diff_archives(base_archive, live_archive)
    base_entries = read_archive_entries(base_archive)
    return _enrich(raw, base_entries)


async def compute_turn_files_diff(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    message_id: str,
    baseline_snapshot_id: str | None,
) -> TurnFilesDiff:
    """Diff the turn baseline zip against the live cloud workspace tree."""
    if not baseline_snapshot_id:
        return TurnFilesDiff(
            message_id=message_id,
            baseline_snapshot_id=None,
            available=False,
            changes=[],
        )

    base_archive = await read_snapshot(
        user_id=user_id,
        folder_id=folder_id,
        conversation_id=conversation_id,
        snapshot_id=baseline_snapshot_id,
    )
    root = resolve_workspace_root(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    live_archive = zip_dir(root)
    return TurnFilesDiff(
        message_id=message_id,
        baseline_snapshot_id=baseline_snapshot_id,
        available=True,
        changes=_diff_archives_enriched(base_archive, live_archive),
    )


def _resolve_local_baseline_zip(
    workspace_root: Path, *, message_id: str, baseline_snapshot_id: str | None
) -> tuple[str, Path] | None:
    """Prefer explicit id; fall back to message_id path convention."""
    candidates: list[str] = []
    if baseline_snapshot_id:
        candidates.append(baseline_snapshot_id)
    if message_id and message_id not in candidates:
        candidates.append(message_id)
    for sid in candidates:
        path = local_baseline_path(workspace_root, sid)
        if path.is_file():
            return sid, path
    return None


def _compute_local_turn_files_diff_sync(
    *,
    workspace_root: Path,
    message_id: str,
    baseline_snapshot_id: str | None,
) -> TurnFilesDiff:
    resolved = _resolve_local_baseline_zip(
        workspace_root,
        message_id=message_id,
        baseline_snapshot_id=baseline_snapshot_id,
    )
    if resolved is None:
        return TurnFilesDiff(
            message_id=message_id,
            baseline_snapshot_id=baseline_snapshot_id,
            available=False,
            changes=[],
        )
    sid, path = resolved
    base_archive = path.read_bytes()
    live_archive = zip_dir(workspace_root)
    return TurnFilesDiff(
        message_id=message_id,
        baseline_snapshot_id=sid,
        available=True,
        changes=_diff_archives_enriched(base_archive, live_archive),
    )


async def compute_local_turn_files_diff(
    *,
    workspace_root: Path,
    message_id: str,
    baseline_snapshot_id: str | None = None,
) -> TurnFilesDiff:
    """Diff local baseline zip vs live workspace (sidecar A1+)."""
    return await asyncio.to_thread(
        _compute_local_turn_files_diff_sync,
        workspace_root=workspace_root,
        message_id=message_id,
        baseline_snapshot_id=baseline_snapshot_id,
    )


def _restore_local_turn_baseline_sync(workspace_root: Path, snapshot_id: str) -> None:
    path = local_baseline_path(workspace_root, snapshot_id)
    if not path.is_file():
        raise FileNotFoundError(f"local baseline not found: {snapshot_id}")
    unzip_into(path.read_bytes(), workspace_root)


async def restore_local_turn_baseline(*, workspace_root: Path, snapshot_id: str) -> None:
    """Overlay the local baseline zip onto the workspace (do not call cloud restore)."""
    await asyncio.to_thread(_restore_local_turn_baseline_sync, workspace_root, snapshot_id)
