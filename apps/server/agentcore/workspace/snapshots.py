"""Workspace snapshot service — conversation → workspace → StorageProvider.

Thin orchestration over ``locate.py`` (path policy) and ``storage`` (the
configured provider). Both the post-turn auto-backup (``conversation/service``)
and the snapshot API routes go through here, so "which conversation → which
storage key / root" lives in exactly one place. Path policy never leaks into the
storage layer; provider choice never leaks into the routes.
"""

from __future__ import annotations

from agentcore.config import settings
from agentcore.storage import SnapshotRef, StorageProvider, build_storage_provider
from agentcore.workspace.locate import resolve_workspace_root, workspace_storage_key


async def _enforce_auto_cap(provider: StorageProvider, key: str, keep: int) -> None:
    """Prune the oldest automatic (unlabeled) snapshots beyond ``keep`` (决策⑥).

    Only auto backups are capped; labeled snapshots (手动留版本) are kept forever.
    ``list_snapshots`` returns newest-first, so the autos past ``keep`` are the
    tail. Best-effort: a prune failure must never fail the snapshot it follows.
    """
    if keep <= 0:
        return
    autos = [s for s in await provider.list_snapshots(key) if not s.label]
    for stale in autos[keep:]:
        await provider.delete_snapshot(key, stale.snapshot_id)


async def create_snapshot(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    label: str | None = None,
) -> SnapshotRef:
    """Snapshot a conversation's workspace. A ``label`` marks a kept version.

    Auto snapshots (no ``label``) are capped to ``workspace_auto_snapshot_max``:
    the oldest auto backups beyond the cap are pruned so they don't grow without
    bound (决策⑥). Kept versions (labeled) are never pruned.
    """
    key = workspace_storage_key(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    root = resolve_workspace_root(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    provider = build_storage_provider()
    ref = await provider.snapshot(root, key, label=label)
    if label is None:
        await _enforce_auto_cap(provider, key, settings.workspace_auto_snapshot_max)
    return ref


async def purge_snapshots(*, user_id: str, folder_id: str | None, conversation_id: str) -> None:
    """Delete the entire snapshot history for a conversation's workspace (决策⑦)."""
    key = workspace_storage_key(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    await build_storage_provider().purge(key)


async def list_snapshots(
    *, user_id: str, folder_id: str | None, conversation_id: str
) -> list[SnapshotRef]:
    """List a conversation's workspace snapshots, newest first."""
    key = workspace_storage_key(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await build_storage_provider().list_snapshots(key)


async def restore_snapshot(
    *, user_id: str, folder_id: str | None, conversation_id: str, snapshot_id: str
) -> None:
    """Extract a snapshot over the conversation's workspace (``SnapshotNotFound``)."""
    key = workspace_storage_key(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    root = resolve_workspace_root(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    await build_storage_provider().restore(key, snapshot_id, root)


async def read_snapshot(
    *, user_id: str, folder_id: str | None, conversation_id: str, snapshot_id: str
) -> bytes:
    """Return a snapshot archive (zip) bytes for download (``SnapshotNotFound``)."""
    key = workspace_storage_key(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await build_storage_provider().read_snapshot(key, snapshot_id)


async def restore_into_workspace(
    *,
    source_user_id: str,
    source_folder_id: str | None,
    source_conversation_id: str,
    snapshot_id: str,
    dest_user_id: str,
    dest_folder_id: str | None,
    dest_conversation_id: str,
) -> None:
    """Restore one conversation's snapshot into *another* conversation's workspace.

    The seeding step of a local→云 handoff (双模式工作区 P2e / e2): the source
    (local) conversation's base snapshot is extracted into the destination (hidden
    cloud job) conversation's freshly-resolved workspace root, so the cloud team
    runs on the user's real files. Distinct from :func:`restore_snapshot`, which
    restores a conversation over its *own* root. Raises ``SnapshotNotFound`` if the
    snapshot id is missing under the source key.
    """
    source_key = workspace_storage_key(
        user_id=source_user_id,
        folder_id=source_folder_id,
        conversation_id=source_conversation_id,
    )
    dest_root = resolve_workspace_root(
        user_id=dest_user_id,
        folder_id=dest_folder_id,
        conversation_id=dest_conversation_id,
    )
    await build_storage_provider().restore(source_key, snapshot_id, dest_root)
