"""Unit tests for the filesystem AssetStorage backend (agentcore.storage.assets)."""

from pathlib import Path

import pytest

from agentcore.storage.assets import FilesystemAssetStorage
from agentcore.storage.protocol import StorageError


async def test_put_get_delete_roundtrip(tmp_path: Path):
    store = FilesystemAssetStorage(base_dir=tmp_path)
    key = "avatars/u1/abc.webp"

    await store.put(key, b"bytes", content_type="image/webp")
    assert await store.get(key) == b"bytes"

    await store.delete(key)
    assert await store.get(key) is None


async def test_get_missing_returns_none(tmp_path: Path):
    store = FilesystemAssetStorage(base_dir=tmp_path)
    assert await store.get("avatars/nope.webp") is None


async def test_delete_missing_is_idempotent(tmp_path: Path):
    store = FilesystemAssetStorage(base_dir=tmp_path)
    # Deleting a key that was never written must not raise.
    await store.delete("avatars/nope.webp")


async def test_put_rejects_traversal_key(tmp_path: Path):
    store = FilesystemAssetStorage(base_dir=tmp_path)
    with pytest.raises(StorageError):
        await store.put("../escape.webp", b"x", content_type="image/webp")


async def test_put_overwrites_existing(tmp_path: Path):
    store = FilesystemAssetStorage(base_dir=tmp_path)
    key = "avatars/u1/x.webp"
    await store.put(key, b"old", content_type="image/webp")
    await store.put(key, b"new", content_type="image/webp")
    assert await store.get(key) == b"new"
