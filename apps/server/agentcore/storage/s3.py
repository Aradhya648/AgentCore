"""S3StorageProvider — snapshots on any S3-compatible object store.

Works against Aliyun OSS (prod), MinIO (dev), or AWS S3 unchanged — the only
difference is endpoint/credentials/bucket in config. boto3 is imported lazily so
the storage package (and the filesystem default) loads without the dependency;
blocking boto3 calls are offloaded to threads. Listing reads a per-key
``manifest.json`` (same scheme as the filesystem provider) rather than relying on
vendor-specific object metadata.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from agentcore.storage._archive import (
    MANIFEST_NAME,
    manifest_from_bytes,
    manifest_to_bytes,
    new_snapshot_id,
    unzip_into,
    zip_dir,
)
from agentcore.storage.protocol import SnapshotNotFound, SnapshotRef, StorageError

_MISSING_CODES = {"NoSuchKey", "NoSuchObject", "404"}


class S3StorageProvider:
    """Snapshot store backed by an S3-compatible bucket."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        prefix: str = "snapshots",
        addressing_style: str = "path",
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as e:  # pragma: no cover - exercised only without boto3
            raise StorageError(
                "boto3 is required for S3 storage; install it or use the filesystem storage backend"
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

    def _key(self, storage_key: str, name: str) -> str:
        parts = [p for p in (self._prefix, storage_key.strip("/"), name) if p]
        return "/".join(parts)

    def _key_prefix(self, storage_key: str) -> str:
        """The object-key prefix for one storage key (trailing slash).

        A trailing ``/`` scopes a ``list_objects_v2`` to exactly this key — never
        a sibling that merely shares the name as a string prefix.
        """
        parts = [p for p in (self._prefix, storage_key.strip("/")) if p]
        return "/".join(parts) + "/"

    def _get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            code = str(e.response.get("Error", {}).get("Code", ""))
            if code in _MISSING_CODES:
                return None
            raise StorageError(f"S3 get_object failed: {e}") from e

    def _put_bytes(self, key: str, data: bytes) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except ClientError as e:
            raise StorageError(f"S3 put_object failed: {e}") from e

    async def snapshot(
        self, workspace_root: Path, storage_key: str, *, label: str | None = None
    ) -> SnapshotRef:
        return await asyncio.to_thread(self._snapshot_sync, workspace_root, storage_key, label)

    def _snapshot_sync(
        self, workspace_root: Path, storage_key: str, label: str | None
    ) -> SnapshotRef:
        data = zip_dir(workspace_root)
        snapshot_id = new_snapshot_id()
        self._put_bytes(self._key(storage_key, f"{snapshot_id}.zip"), data)
        ref = SnapshotRef(
            snapshot_id=snapshot_id,
            label=label,
            created_at=datetime.now(UTC),
            size_bytes=len(data),
        )
        refs = manifest_from_bytes(self._get_bytes(self._key(storage_key, MANIFEST_NAME)))
        refs.insert(0, ref)
        self._put_bytes(self._key(storage_key, MANIFEST_NAME), manifest_to_bytes(refs))
        return ref

    async def list_snapshots(self, storage_key: str) -> list[SnapshotRef]:
        return await asyncio.to_thread(self._list_sync, storage_key)

    def _list_sync(self, storage_key: str) -> list[SnapshotRef]:
        refs = manifest_from_bytes(self._get_bytes(self._key(storage_key, MANIFEST_NAME)))
        return sorted(refs, key=lambda r: r.created_at, reverse=True)

    async def restore(self, storage_key: str, snapshot_id: str, workspace_root: Path) -> None:
        await asyncio.to_thread(self._restore_sync, storage_key, snapshot_id, workspace_root)

    def _restore_sync(self, storage_key: str, snapshot_id: str, workspace_root: Path) -> None:
        data = self._get_bytes(self._key(storage_key, f"{snapshot_id}.zip"))
        if data is None:
            raise SnapshotNotFound(snapshot_id)
        unzip_into(data, workspace_root)

    async def read_snapshot(self, storage_key: str, snapshot_id: str) -> bytes:
        return await asyncio.to_thread(self._read_snapshot_sync, storage_key, snapshot_id)

    def _read_snapshot_sync(self, storage_key: str, snapshot_id: str) -> bytes:
        data = self._get_bytes(self._key(storage_key, f"{snapshot_id}.zip"))
        if data is None:
            raise SnapshotNotFound(snapshot_id)
        return data

    async def delete_snapshot(self, storage_key: str, snapshot_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, storage_key, snapshot_id)

    def _delete_sync(self, storage_key: str, snapshot_id: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.delete_object(
                Bucket=self._bucket, Key=self._key(storage_key, f"{snapshot_id}.zip")
            )
        except ClientError as e:
            raise StorageError(f"S3 delete_object failed: {e}") from e
        refs = manifest_from_bytes(self._get_bytes(self._key(storage_key, MANIFEST_NAME)))
        kept = [r for r in refs if r.snapshot_id != snapshot_id]
        if len(kept) != len(refs):
            self._put_bytes(self._key(storage_key, MANIFEST_NAME), manifest_to_bytes(kept))

    async def purge(self, storage_key: str) -> None:
        await asyncio.to_thread(self._purge_sync, storage_key)

    def _purge_sync(self, storage_key: str) -> None:
        from botocore.exceptions import ClientError

        prefix = self._key_prefix(storage_key)
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            batch: list[dict] = []
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    batch.append({"Key": obj["Key"]})
                    # delete_objects caps at 1000 keys per request.
                    if len(batch) == 1000:
                        self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": batch})
                        batch = []
            if batch:
                self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": batch})
        except ClientError as e:
            raise StorageError(f"S3 purge failed: {e}") from e
