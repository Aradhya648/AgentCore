"""Archive + manifest helpers shared by storage providers.

A snapshot is a single zip of the workspace tree (regenerable junk pruned). Per
``storage_key`` a small ``manifest.json`` lists the snapshots, so listing is one
object read and does not depend on per-object metadata (which differs across S3
vendors). Manifest writes for one key are serialized by the app's folder-level
lock (决策④), so the read-modify-write here needs no extra coordination for MVP.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentcore.storage.protocol import SnapshotRef
from agentcore.workspace._paths import IGNORED_DIRS

MANIFEST_NAME = "manifest.json"


def new_snapshot_id() -> str:
    """Time-sortable id: ``YYYYMMDDTHHMMSSZ-<short>`` (UTC + random suffix)."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


class ArchiveLimitError(Exception):
    """Raised when ``zip_dir`` hits a file-count or byte-size gate."""

    def __init__(self, *, reason: str, file_count: int, total_bytes: int) -> None:
        self.reason = reason
        self.file_count = file_count
        self.total_bytes = total_bytes
        super().__init__(f"archive limit exceeded: {reason}")


def zip_dir(
    root: Path,
    *,
    max_files: int | None = None,
    max_bytes: int | None = None,
) -> bytes:
    """Archive a directory tree to in-memory zip bytes.

    Prunes VCS/dependency/cache noise (``IGNORED_DIRS``) and skips symlinks so a
    snapshot can't follow a link out of the tree. Paths are stored POSIX-relative
    to ``root``.

    Optional ``max_files`` / ``max_bytes`` (raw file bytes before zip) align with
    the desktop handoff gate; exceeding either raises :exc:`ArchiveLimitError`.
    """
    buf = io.BytesIO()
    file_count = 0
    total_bytes = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
            for fname in sorted(filenames):
                full = Path(dirpath) / fname
                if full.is_symlink() or not full.is_file():
                    continue
                if max_files is not None and file_count >= max_files:
                    raise ArchiveLimitError(
                        reason="max_files",
                        file_count=file_count,
                        total_bytes=total_bytes,
                    )
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                if max_bytes is not None and total_bytes + size > max_bytes:
                    raise ArchiveLimitError(
                        reason="max_bytes",
                        file_count=file_count,
                        total_bytes=total_bytes,
                    )
                arcname = full.relative_to(root).as_posix()
                zf.write(full, arcname)
                file_count += 1
                total_bytes += size
    return buf.getvalue()


def unzip_into(data: bytes, root: Path) -> None:
    """Extract zip ``data`` over ``root`` (creating it), guarding against zip-slip."""
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            target = (root / member).resolve()
            # Reject any entry that would land outside the workspace root.
            if target != root_resolved and root_resolved not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())


def manifest_to_bytes(refs: list[SnapshotRef]) -> bytes:
    """Serialize the snapshot list to manifest JSON bytes (newest first)."""
    payload = {
        "snapshots": [
            {
                "snapshot_id": r.snapshot_id,
                "label": r.label,
                "created_at": r.created_at.isoformat(),
                "size_bytes": r.size_bytes,
            }
            for r in refs
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def manifest_from_bytes(data: bytes | None) -> list[SnapshotRef]:
    """Parse manifest bytes into a snapshot list (empty for missing/blank)."""
    if not data:
        return []
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    refs: list[SnapshotRef] = []
    for item in raw.get("snapshots", []):
        try:
            refs.append(
                SnapshotRef(
                    snapshot_id=item["snapshot_id"],
                    label=item.get("label"),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    size_bytes=int(item.get("size_bytes", 0)),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return refs
