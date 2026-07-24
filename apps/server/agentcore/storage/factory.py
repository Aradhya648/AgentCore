"""Build the configured StorageProvider (project house-style factory).

Mirrors ``llm/factory.py``: one place decides which implementation to use from
settings. ``auto`` picks S3 when credentials + bucket are present, otherwise the
zero-config filesystem provider (dev / tests). The result is cached so the S3
client (and its connection pool) is created once per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agentcore.config import settings
from agentcore.storage.filesystem import FilesystemStorageProvider
from agentcore.storage.protocol import StorageProvider


def _use_s3() -> bool:
    backend = (settings.storage_backend or "auto").lower()
    if backend == "s3":
        return True
    if backend == "filesystem":
        return False
    # auto: S3 only when it is actually configured.
    return bool(settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key)


@lru_cache(maxsize=1)
def build_storage_provider() -> StorageProvider:
    """Return the process-wide StorageProvider chosen by configuration."""
    if _use_s3():
        from agentcore.storage.s3 import S3StorageProvider

        return S3StorageProvider(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url or None,
            region=settings.s3_region or None,
            access_key=settings.s3_access_key_id or None,
            secret_key=settings.s3_secret_access_key or None,
            addressing_style=settings.s3_addressing_style or "path",
        )
    return FilesystemStorageProvider(base_dir=Path(settings.data_dir) / "snapshots")
