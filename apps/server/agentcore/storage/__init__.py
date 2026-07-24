"""Workspace snapshot storage (axis-3 persistence).

``StorageProvider`` snapshots a workspace to object storage for backup, kept
versions, cross-device handoff, and download — separate from ``WorkspaceBackend``
(live files + execution). ``build_storage_provider`` returns the configured impl
(filesystem default, S3-compatible for Aliyun OSS / MinIO).
"""

from agentcore.storage.factory import build_storage_provider
from agentcore.storage.filesystem import FilesystemStorageProvider
from agentcore.storage.protocol import (
    SnapshotNotFound,
    SnapshotRef,
    StorageError,
    StorageProvider,
)

__all__ = [
    "StorageProvider",
    "StorageError",
    "SnapshotNotFound",
    "SnapshotRef",
    "FilesystemStorageProvider",
    "build_storage_provider",
]
