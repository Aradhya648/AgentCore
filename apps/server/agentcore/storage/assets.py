"""AssetStorage — small immutable blobs keyed by path (头像等用户资产).

Deliberately separate from ``StorageProvider`` (which owns *snapshot* persistence —
zip archives + manifests, see ``protocol.py``): an avatar is a single small object
fetched on every render, not a versioned workspace archive. This is the minimal
"put/get/delete one object by key" seam, with the same two-implementation house
style (filesystem for dev/tests, S3 for prod) behind a cached factory, reusing the
same S3 config as the snapshot provider.

Keys are caller-minted and content-addressed (e.g. ``avatars/<user_id>/<hash>.webp``)
so a URL can be cached forever and a re-upload changes the key. The store itself is
agnostic to that scheme — it only reads/writes bytes at a key.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from agentcore.config import settings
from agentcore.storage.protocol import StorageError

_MISSING_CODES = {"NoSuchKey", "NoSuchObject", "404"}


class AssetStorage(Protocol):
    """Read/write/delete a single small object by logical key."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store ``data`` at ``key`` (overwriting any existing object)."""
        ...

    async def get(self, key: str) -> bytes | None:
        """Return the object bytes at ``key``, or ``None`` if it does not exist."""
        ...

    async def delete(self, key: str) -> None:
        """Delete the object at ``key`` (idempotent: a missing key is not an error)."""
        ...


def _safe_relative(key: str) -> Path:
    """Resolve a storage key to a relative path, rejecting traversal.

    Keys are server-minted, but normalise + reject ``..``/absolute segments anyway
    (defense in depth — the filesystem store must never write outside its base).
    """
    rel = Path(key)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise StorageError(f"unsafe asset key: {key!r}")
    return rel


class FilesystemAssetStorage:
    """Asset store on the local disk under ``base_dir`` (dev / tests, zero infra)."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _path(self, key: str) -> Path:
        return (self._base / _safe_relative(key)).resolve()

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(self._put_sync, key, data)

    def _put_sync(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, key)

    def _delete_sync(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3AssetStorage:
    """Asset store on any S3-compatible bucket (prod), under a ``prefix``."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        prefix: str = "assets",
        addressing_style: str = "path",
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as e:  # pragma: no cover - exercised only without boto3
            raise StorageError(
                "boto3 is required for S3 asset storage; install it or use the "
                "filesystem storage backend"
            ) from e

        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            config=Config(s3={"addressing_style": addressing_style}),
        )

    def _key(self, key: str) -> str:
        return "/".join(p for p in (self._prefix, key.strip("/")) if p)

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(self._put_sync, key, data, content_type)

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=self._key(key),
                Body=data,
                ContentType=content_type,
            )
        except ClientError as e:
            raise StorageError(f"S3 put_object failed: {e}") from e

    async def get(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
            return resp["Body"].read()
        except ClientError as e:
            code = str(e.response.get("Error", {}).get("Code", ""))
            if code in _MISSING_CODES:
                return None
            raise StorageError(f"S3 get_object failed: {e}") from e

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, key)

    def _delete_sync(self, key: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.delete_object(Bucket=self._bucket, Key=self._key(key))
        except ClientError as e:
            raise StorageError(f"S3 delete_object failed: {e}") from e


def _use_s3() -> bool:
    """Same backend selection as the snapshot provider (storage_backend / auto)."""
    backend = (settings.storage_backend or "auto").lower()
    if backend == "s3":
        return True
    if backend == "filesystem":
        return False
    return bool(settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key)


@lru_cache(maxsize=1)
def build_asset_storage() -> AssetStorage:
    """Return the process-wide AssetStorage chosen by configuration."""
    if _use_s3():
        return S3AssetStorage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url or None,
            region=settings.s3_region or None,
            access_key=settings.s3_access_key_id or None,
            secret_key=settings.s3_secret_access_key or None,
            addressing_style=settings.s3_addressing_style or "path",
        )
    return FilesystemAssetStorage(base_dir=Path(settings.data_dir) / "assets")
