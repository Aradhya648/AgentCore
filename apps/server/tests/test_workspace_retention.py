"""Unit tests for retention purge helpers (决策⑦), DB-free.

Exercises the filesystem side of a purge — workspace directory + snapshot history
removed for a folder/conversation key — under a redirected ``data_dir`` so the
real tree is never touched. The full DB-driven sweep is covered by the
integration test (needs PostgreSQL).
"""

from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.storage.factory import build_storage_provider
from agentcore.workspace.locate import resolve_workspace_root, workspace_root_path
from agentcore.workspace.retention import (
    _purge_conversation_space,
    purge_folder_space,
    run_retention_sweep,
)
from agentcore.workspace.snapshots import create_snapshot, list_snapshots


@pytest.fixture
def fs_storage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    build_storage_provider.cache_clear()
    try:
        yield
    finally:
        build_storage_provider.cache_clear()


async def test_purge_folder_space_removes_dir_and_snapshots(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "proj.txt").write_text("data", encoding="utf-8")
    await create_snapshot(user_id="u1", folder_id="f1", conversation_id="c1")

    await purge_folder_space(user_id="u1", folder_id="f1")

    assert not workspace_root_path(user_id="u1", folder_id="f1", conversation_id="x").exists()
    # Snapshot history for the folder key is gone too.
    assert await list_snapshots(user_id="u1", folder_id="f1", conversation_id="x") == []


async def test_purge_conversation_space_removes_own_space(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id=None, conversation_id="c9")
    (root / "note.txt").write_text("data", encoding="utf-8")
    await create_snapshot(user_id="u1", folder_id=None, conversation_id="c9")

    await _purge_conversation_space(user_id="u1", conversation_id="c9", folder_id=None)

    assert not workspace_root_path(user_id="u1", folder_id=None, conversation_id="c9").exists()
    assert await list_snapshots(user_id="u1", folder_id=None, conversation_id="c9") == []


async def test_purge_conversation_space_skips_project_member(fs_storage):
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "shared.txt").write_text("data", encoding="utf-8")

    await _purge_conversation_space(user_id="u1", conversation_id="c1", folder_id="f1")

    assert workspace_root_path(user_id="u1", folder_id="f1", conversation_id="c1").exists()


async def test_purge_is_idempotent_on_missing(fs_storage):
    # Purging a never-created space must not raise (idempotent cleanup).
    await purge_folder_space(user_id="u1", folder_id="ghost")
    await _purge_conversation_space(user_id="u1", conversation_id="ghost", folder_id=None)


async def test_sweep_disabled_is_noop(fs_storage, monkeypatch):
    monkeypatch.setattr(settings, "workspace_retention_enabled", False)
    assert await run_retention_sweep() == {"folders": 0, "conversations": 0}
