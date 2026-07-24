"""Tests for the workspace snapshot storage layer (axis-3 persistence).

Covers the FilesystemStorageProvider round-trip (snapshot → list → read →
restore → delete), kept-version labels, newest-first ordering, the typed
``SnapshotNotFound`` failure, the archive helpers (junk pruning + zip-slip
guard), and the factory's backend selection. Hermetic: every snapshot lives
under ``tmp_path``; no external infra and the S3 path is never network-touched.
"""

from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.storage import (
    FilesystemStorageProvider,
    SnapshotNotFound,
    build_storage_provider,
)
from agentcore.storage._archive import unzip_into, zip_dir


def _seed(root: Path) -> None:
    """A small workspace tree with a junk dir that snapshots must prune."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "note.md").write_text("# note\n", encoding="utf-8")
    junk = root / "node_modules"
    junk.mkdir()
    (junk / "huge.js").write_text("x" * 1000, encoding="utf-8")


# --- FilesystemStorageProvider round-trip ---


async def test_snapshot_then_read_and_restore(tmp_path: Path):
    ws = tmp_path / "ws"
    _seed(ws)
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")

    ref = await provider.snapshot(ws, "workspaces/u1/f1")
    assert ref.size_bytes > 0
    assert ref.label is None

    # The archive is downloadable as bytes.
    data = await provider.read_snapshot("workspaces/u1/f1", ref.snapshot_id)
    assert data[:2] == b"PK"  # zip magic

    # Restore into a fresh dir reproduces the tree (minus pruned junk).
    dest = tmp_path / "restored"
    await provider.restore("workspaces/u1/f1", ref.snapshot_id, dest)
    assert (dest / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (dest / "sub" / "note.md").read_text(encoding="utf-8") == "# note\n"
    assert not (dest / "node_modules").exists()  # junk pruned by zip_dir


async def test_label_marks_kept_version(tmp_path: Path):
    ws = tmp_path / "ws"
    _seed(ws)
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")
    ref = await provider.snapshot(ws, "k", label="before refactor")
    assert ref.label == "before refactor"
    listed = await provider.list_snapshots("k")
    assert listed[0].label == "before refactor"


async def test_list_is_newest_first(tmp_path: Path):
    ws = tmp_path / "ws"
    _seed(ws)
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")
    first = await provider.snapshot(ws, "k")
    second = await provider.snapshot(ws, "k")
    listed = await provider.list_snapshots("k")
    assert [r.snapshot_id for r in listed][:2] == [second.snapshot_id, first.snapshot_id]


async def test_list_empty_key_returns_empty(tmp_path: Path):
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")
    assert await provider.list_snapshots("never/used") == []


async def test_restore_unknown_id_raises(tmp_path: Path):
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")
    with pytest.raises(SnapshotNotFound):
        await provider.restore("k", "nope", tmp_path / "out")


async def test_read_unknown_id_raises(tmp_path: Path):
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")
    with pytest.raises(SnapshotNotFound):
        await provider.read_snapshot("k", "nope")


async def test_delete_removes_from_manifest_and_is_idempotent(tmp_path: Path):
    ws = tmp_path / "ws"
    _seed(ws)
    provider = FilesystemStorageProvider(base_dir=tmp_path / "snaps")
    ref = await provider.snapshot(ws, "k")
    await provider.delete_snapshot("k", ref.snapshot_id)
    assert await provider.list_snapshots("k") == []
    # Deleting again is not an error.
    await provider.delete_snapshot("k", ref.snapshot_id)
    with pytest.raises(SnapshotNotFound):
        await provider.read_snapshot("k", ref.snapshot_id)


# --- archive helpers ---


def test_zip_dir_prunes_junk_and_keeps_real_files(tmp_path: Path):
    ws = tmp_path / "ws"
    _seed(ws)
    names = _zip_names(zip_dir(ws))
    assert "main.py" in names
    assert "sub/note.md" in names
    assert not any(n.startswith("node_modules/") for n in names)


def test_unzip_rejects_zip_slip(tmp_path: Path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ok.txt", "safe")
        zf.writestr("../escape.txt", "evil")  # path-traversal entry
    dest = tmp_path / "out"
    unzip_into(buf.getvalue(), dest)
    assert (dest / "ok.txt").read_text(encoding="utf-8") == "safe"
    assert not (tmp_path / "escape.txt").exists()  # traversal entry dropped


def _zip_names(data: bytes) -> list[str]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.namelist()


# --- factory selection ---


def _clear_factory_cache() -> None:
    build_storage_provider.cache_clear()


def test_factory_filesystem_when_forced(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    _clear_factory_cache()
    try:
        assert isinstance(build_storage_provider(), FilesystemStorageProvider)
    finally:
        _clear_factory_cache()


def test_factory_auto_without_credentials_is_filesystem(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "auto")
    monkeypatch.setattr(settings, "s3_access_key_id", "")
    monkeypatch.setattr(settings, "s3_secret_access_key", "")
    _clear_factory_cache()
    try:
        assert isinstance(build_storage_provider(), FilesystemStorageProvider)
    finally:
        _clear_factory_cache()


def test_factory_auto_with_credentials_selects_s3(monkeypatch):
    from agentcore.storage.s3 import S3StorageProvider

    monkeypatch.setattr(settings, "storage_backend", "auto")
    monkeypatch.setattr(settings, "s3_bucket", "bucket")
    monkeypatch.setattr(settings, "s3_access_key_id", "key")
    monkeypatch.setattr(settings, "s3_secret_access_key", "secret")
    _clear_factory_cache()
    try:
        # Constructs a boto3 client (no network until a call is made).
        assert isinstance(build_storage_provider(), S3StorageProvider)
    finally:
        _clear_factory_cache()
