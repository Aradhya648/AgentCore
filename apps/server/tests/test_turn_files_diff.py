"""Tests for A1+ turn baseline / files diff (cloud + local)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.storage._archive import ArchiveLimitError, zip_dir
from agentcore.workspace.handoff_diff import diff_archives, read_archive_entries
from agentcore.workspace.turn_baseline import (
    LOCAL_BASELINE_MAX_FILES,
    local_baseline_path,
    maybe_capture_turn_baseline,
)
from agentcore.workspace.turn_diff import (
    _enrich,
    compute_local_turn_files_diff,
    compute_turn_files_diff,
    restore_local_turn_baseline,
)


@pytest.mark.asyncio
async def test_diff_archives_enrich_includes_base_content(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "a.txt").write_bytes(b"hello\n")
    (after / "a.txt").write_bytes(b"hello\nworld\n")
    (after / "b.txt").write_bytes(b"new\n")

    changes = diff_archives(zip_dir(before), zip_dir(after))
    enriched = _enrich(changes, read_archive_entries(zip_dir(before)))
    by_path = {c.path: c for c in enriched}
    assert by_path["a.txt"].change_type == "modified"
    assert by_path["a.txt"].base_content == "hello\n"
    assert by_path["a.txt"].content == "hello\nworld\n"
    assert by_path["b.txt"].change_type == "added"
    assert by_path["b.txt"].base_content is None


@pytest.mark.asyncio
async def test_compute_turn_files_diff_unavailable_without_baseline():
    result = await compute_turn_files_diff(
        user_id="u1",
        folder_id=None,
        conversation_id="c1",
        message_id="m1",
        baseline_snapshot_id=None,
    )
    assert result.available is False
    assert result.changes == []


@pytest.mark.asyncio
async def test_local_baseline_capture_writes_zip(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    backend = SimpleNamespace(location="local")

    sid = await maybe_capture_turn_baseline(
        user_id="u1",
        folder_id=None,
        conversation_id="c1",
        message_id="msg-abc",
        backend=backend,
        workspace_root=root,
    )
    assert sid == "msg-abc"
    zip_path = local_baseline_path(root, "msg-abc")
    assert zip_path.is_file()
    # .agentcore itself is pruned from the archive.
    entries = read_archive_entries(zip_path.read_bytes())
    assert "src/a.py" in entries
    assert not any(p.startswith(".agentcore/") for p in entries)


@pytest.mark.asyncio
async def test_local_baseline_skips_on_file_cap(tmp_path: Path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    for i in range(5):
        (root / f"f{i}.txt").write_text("x", encoding="utf-8")
    backend = SimpleNamespace(location="local")
    monkeypatch.setattr(
        "agentcore.workspace.turn_baseline.LOCAL_BASELINE_MAX_FILES",
        2,
    )

    sid = await maybe_capture_turn_baseline(
        user_id="u1",
        folder_id=None,
        conversation_id="c1",
        message_id="msg-cap",
        backend=backend,
        workspace_root=root,
    )
    assert sid is None
    assert not local_baseline_path(root, "msg-cap").exists()


@pytest.mark.asyncio
async def test_zip_dir_raises_archive_limit(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")
    (root / "b.txt").write_bytes(b"world")
    with pytest.raises(ArchiveLimitError) as ei:
        zip_dir(root, max_files=1)
    assert ei.value.reason == "max_files"


@pytest.mark.asyncio
async def test_local_diff_and_restore(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    backend = SimpleNamespace(location="local")
    sid = await maybe_capture_turn_baseline(
        user_id="u1",
        folder_id=None,
        conversation_id="c1",
        message_id="m-diff",
        backend=backend,
        workspace_root=root,
    )
    assert sid == "m-diff"

    (root / "a.txt").write_text("new\n", encoding="utf-8")
    (root / "b.txt").write_text("added\n", encoding="utf-8")

    diff = await compute_local_turn_files_diff(
        workspace_root=root, message_id="m-diff"
    )
    assert diff.available is True
    assert diff.baseline_snapshot_id == "m-diff"
    by_path = {c.path: c for c in diff.changes}
    assert by_path["a.txt"].change_type == "modified"
    assert by_path["a.txt"].base_content is not None
    assert by_path["a.txt"].base_content.replace("\r\n", "\n") == "old\n"
    assert by_path["a.txt"].content is not None
    assert by_path["a.txt"].content.replace("\r\n", "\n") == "new\n"
    assert by_path["b.txt"].change_type == "added"

    await restore_local_turn_baseline(workspace_root=root, snapshot_id="m-diff")
    assert (root / "a.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == "old\n"
    # Overlay restore does not delete post-baseline adds (same as cloud unzip).
    assert (root / "b.txt").is_file()


@pytest.mark.asyncio
async def test_local_diff_unavailable_without_zip(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    diff = await compute_local_turn_files_diff(
        workspace_root=root, message_id="missing"
    )
    assert diff.available is False
    assert diff.changes == []


@pytest.mark.asyncio
async def test_cloud_location_still_skips_without_snapshot_setting(
    tmp_path: Path, monkeypatch
):
    """Server location without snapshot feature → None (unchanged cloud gate)."""
    from agentcore.config import settings

    monkeypatch.setattr(settings, "workspace_snapshot_enabled", False)
    backend = SimpleNamespace(location="server")
    sid = await maybe_capture_turn_baseline(
        user_id="u1",
        folder_id=None,
        conversation_id="c1",
        message_id="m1",
        backend=backend,
        workspace_root=tmp_path,
    )
    assert sid is None


def test_local_baseline_max_files_aligned_with_desktop_gate():
    # Keep in sync with apps/desktop/.../fs/constants.ts ARCHIVE_MAX_FILES.
    assert LOCAL_BASELINE_MAX_FILES == 20_000


@pytest.mark.asyncio
async def test_get_turn_files_diff_route_passes_folder_id():
    """S6 regression: route must use `_get_owned_conversation` (returns row), not the
    void ownership guard — otherwise ``conv.folder_id`` raises AttributeError → 500.
    """
    from agentcore.api.routes.conversations.turn_files_diff import get_turn_files_diff

    user = SimpleNamespace(user_id="u1")
    conv = SimpleNamespace(id="c1", folder_id="folder-xyz")
    msg = SimpleNamespace(role="assistant", baseline_snapshot_id="snap-1")
    conv_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=conv))
    msg_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=msg))
    fake = SimpleNamespace(baseline_snapshot_id="snap-1", available=True, changes=[])

    with patch(
        "agentcore.api.routes.conversations.turn_files_diff.compute_turn_files_diff",
        new=AsyncMock(return_value=fake),
    ) as compute:
        resp = await get_turn_files_diff(
            conversation_id="c1",
            message_id="m1",
            user=user,
            conv_repo=conv_repo,
            msg_repo=msg_repo,
        )

    compute.assert_awaited_once()
    assert compute.await_args.kwargs["folder_id"] == "folder-xyz"
    assert compute.await_args.kwargs["conversation_id"] == "c1"
    assert compute.await_args.kwargs["message_id"] == "m1"
    assert compute.await_args.kwargs["baseline_snapshot_id"] == "snap-1"
    assert resp.available is True
    assert resp.total == 0
