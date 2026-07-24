"""Tests for the snapshot service (conversation → workspace → StorageProvider).

End-to-end over the filesystem backend: resolves a conversation's workspace via
``locate``, snapshots it, lists/reads/restores it. ``data_dir`` and the storage
backend are redirected to ``tmp_path`` so nothing touches the real ./data tree;
the lru-cached factory is cleared around each test so the redirect takes effect.
"""

from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.storage import SnapshotNotFound
from agentcore.storage.factory import build_storage_provider
from agentcore.workspace.locate import resolve_workspace_root
from agentcore.workspace.snapshots import (
    create_snapshot,
    list_snapshots,
    purge_snapshots,
    read_snapshot,
    restore_snapshot,
)


@pytest.fixture
def fs_storage(tmp_path: Path, monkeypatch):
    """Redirect data_dir + force the filesystem backend, with a clean factory cache."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    build_storage_provider.cache_clear()
    try:
        yield
    finally:
        build_storage_provider.cache_clear()


async def test_create_then_list_and_download(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "report.md").write_text("done", encoding="utf-8")

    ref = await create_snapshot(user_id="u1", folder_id="f1", conversation_id="c1")
    listed = await list_snapshots(user_id="u1", folder_id="f1", conversation_id="c1")
    assert [r.snapshot_id for r in listed] == [ref.snapshot_id]

    data = await read_snapshot(
        user_id="u1", folder_id="f1", conversation_id="c1", snapshot_id=ref.snapshot_id
    )
    assert data[:2] == b"PK"


async def test_restore_recovers_deleted_file(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id=None, conversation_id="c9")
    (root / "keep.txt").write_text("v1", encoding="utf-8")
    ref = await create_snapshot(user_id="u1", folder_id=None, conversation_id="c9")

    # User (or agent) wipes the file after the snapshot.
    (root / "keep.txt").unlink()
    assert not (root / "keep.txt").exists()

    await restore_snapshot(
        user_id="u1", folder_id=None, conversation_id="c9", snapshot_id=ref.snapshot_id
    )
    assert (root / "keep.txt").read_text(encoding="utf-8") == "v1"


async def test_project_snapshots_are_shared(fs_storage):
    """Sibling conversations in the same project share snapshot history."""
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "shared.txt").write_text("x", encoding="utf-8")
    ref = await create_snapshot(user_id="u1", folder_id="f1", conversation_id="c1")

    listed_c2 = await list_snapshots(user_id="u1", folder_id="f1", conversation_id="c2")
    assert ref.snapshot_id in {r.snapshot_id for r in listed_c2}


async def test_label_is_preserved(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "a.txt").write_text("x", encoding="utf-8")
    await create_snapshot(user_id="u1", folder_id="f1", conversation_id="c1", label="milestone")
    listed = await list_snapshots(user_id="u1", folder_id="f1", conversation_id="c1")
    assert listed[0].label == "milestone"


async def test_read_unknown_snapshot_raises(fs_storage):
    resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    with pytest.raises(SnapshotNotFound):
        await read_snapshot(
            user_id="u1", folder_id="f1", conversation_id="c1", snapshot_id="missing"
        )


async def test_auto_snapshot_cap_prunes_oldest(fs_storage, monkeypatch):
    monkeypatch.setattr(settings, "workspace_auto_snapshot_max", 3)
    root = resolve_workspace_root(user_id="u1", folder_id=None, conversation_id="cap")
    (root / "f.txt").write_text("x", encoding="utf-8")

    refs = [
        await create_snapshot(user_id="u1", folder_id=None, conversation_id="cap") for _ in range(5)
    ]
    listed = await list_snapshots(user_id="u1", folder_id=None, conversation_id="cap")
    # Only the 3 newest auto snapshots survive; the 2 oldest were pruned.
    assert {r.snapshot_id for r in listed} == {r.snapshot_id for r in refs[-3:]}


async def test_labeled_snapshots_survive_cap(fs_storage, monkeypatch):
    monkeypatch.setattr(settings, "workspace_auto_snapshot_max", 1)
    root = resolve_workspace_root(user_id="u1", folder_id=None, conversation_id="kept")
    (root / "f.txt").write_text("x", encoding="utf-8")

    kept = await create_snapshot(user_id="u1", folder_id=None, conversation_id="kept", label="v1")
    # Several auto snapshots that would blow past the cap of 1.
    for _ in range(3):
        await create_snapshot(user_id="u1", folder_id=None, conversation_id="kept")

    listed = await list_snapshots(user_id="u1", folder_id=None, conversation_id="kept")
    labels = [r.snapshot_id for r in listed if r.label == "v1"]
    autos = [r for r in listed if not r.label]
    assert kept.snapshot_id in labels  # the kept version is never pruned
    assert len(autos) == 1  # autos still capped


async def test_purge_snapshots_clears_history(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "a.txt").write_text("x", encoding="utf-8")
    await create_snapshot(user_id="u1", folder_id="f1", conversation_id="c1")
    await create_snapshot(user_id="u1", folder_id="f1", conversation_id="c1", label="v1")

    await purge_snapshots(user_id="u1", folder_id="f1", conversation_id="c1")
    listed = await list_snapshots(user_id="u1", folder_id="f1", conversation_id="c1")
    assert listed == []
