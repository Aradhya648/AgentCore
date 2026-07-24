"""Handoff result diff — base vs result snapshot → a change set for the local apply.

The third stage of a local→云 handoff (双模式工作区 P2e / e3): once a cloud team run
succeeds, its result snapshot is compared against the base snapshot it ran on,
yielding a per-file change set (added / modified / deleted) the desktop replays onto
the user's local files. Diffing happens directly on the two snapshot *zips* — a
snapshot is one zip of the workspace tree (``storage/_archive``), so reading both
archives and comparing entries by path + content hash is the whole job; no temp
extraction, and it never touches the user's machine.

Three-way conflict detection (the user may have edited locally while the cloud ran)
is :func:`classify_three_way`: the change set carries each file's base hash, the
desktop hashes its current local copy, and the verdict decides clean / already-
applied / conflict per file. The classifier lives here as the single source of truth
(unit-tested), rather than being re-implemented in the client.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from typing import Literal

from agentcore.storage import build_storage_provider
from agentcore.workspace.locate import workspace_storage_key

ChangeType = Literal["added", "modified", "deleted"]
ThreeWay = Literal["clean", "applied", "conflict"]


@dataclass(frozen=True)
class FileChange:
    """One file's base→result delta in a handoff result (双模式工作区 P2e / e3).

    ``base_sha`` / ``result_sha`` are sha256 hex of the file's bytes on each side
    (``None`` where the file is absent: ``base_sha`` for an add, ``result_sha`` for
    a delete). ``content`` is the result's text for an add/modify when it decodes as
    UTF-8 (so the client can write + preview it inline), else ``None`` — a binary
    result carries no inline text (``is_binary`` is set) and is fetched via snapshot
    download instead. ``size_bytes`` is the result file size (0 for a delete).
    """

    path: str
    change_type: ChangeType
    base_sha: str | None
    result_sha: str | None
    is_binary: bool
    content: str | None
    size_bytes: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_text(data: bytes) -> str | None:
    """Decode bytes as UTF-8 text, or ``None`` when binary.

    A NUL byte is the cheap binary tell (UTF-8 text never contains one); otherwise a
    strict UTF-8 decode decides. Binary results are not inlined — the client pulls
    them from the snapshot download.
    """
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_archive_entries(archive: bytes) -> dict[str, bytes]:
    """Map POSIX path → file bytes for every file entry in a snapshot zip.

    Directory entries (trailing ``/``) are skipped; the archive is built by
    ``storage/_archive.zip_dir`` with POSIX-relative names, so paths line up with
    what the desktop addresses files by. Shared by :func:`diff_archives` and the e3
    apply (which needs the *result* bytes to write back, including binary files the
    diff does not inline).
    """
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            with zf.open(member) as src:
                entries[member] = src.read()
    return entries


def diff_archives(base_archive: bytes, result_archive: bytes) -> list[FileChange]:
    """Diff two snapshot zips into a per-file change set, sorted by path.

    A path present only in the result is ``added``; present on both with differing
    bytes is ``modified`` (identical bytes are omitted — nothing to apply); present
    only in the base is ``deleted``. Hashes bracket each side for the client's
    three-way check, and the result's text is inlined when it decodes as UTF-8.
    """
    base = read_archive_entries(base_archive)
    result = read_archive_entries(result_archive)
    changes: list[FileChange] = []

    for path in sorted(set(base) | set(result)):
        b = base.get(path)
        r = result.get(path)
        if b is not None and r is not None:
            if b == r:
                continue
            text = _decode_text(r)
            changes.append(
                FileChange(
                    path=path,
                    change_type="modified",
                    base_sha=_sha256(b),
                    result_sha=_sha256(r),
                    is_binary=text is None,
                    content=text,
                    size_bytes=len(r),
                )
            )
        elif r is not None:
            text = _decode_text(r)
            changes.append(
                FileChange(
                    path=path,
                    change_type="added",
                    base_sha=None,
                    result_sha=_sha256(r),
                    is_binary=text is None,
                    content=text,
                    size_bytes=len(r),
                )
            )
        else:
            changes.append(
                FileChange(
                    path=path,
                    change_type="deleted",
                    base_sha=_sha256(b),  # type: ignore[arg-type]  # b not None here
                    result_sha=None,
                    is_binary=False,
                    content=None,
                    size_bytes=0,
                )
            )
    return changes


def classify_three_way(
    *, base_sha: str | None, result_sha: str | None, local_sha: str | None
) -> ThreeWay:
    """Three-way verdict for applying one result change onto the live local file.

    ``base_sha`` is what the cloud started from, ``result_sha`` the cloud output,
    ``local_sha`` the user's current local copy (each ``None`` when the file is
    absent on that side). The desktop hashes its local copy and calls this per
    changed file before applying:

    - ``applied`` — local already equals the result: nothing to do (idempotent re-apply).
    - ``clean`` — local still matches the base the cloud started from: the change applies cleanly.
    - ``conflict`` — local diverged from both: the user edited it while the cloud
      ran, so the change needs a manual pick (标红逐文件选).

    The two equality checks collapse the full add/modify/delete table: e.g. a delete
    (``result_sha`` None) is ``applied`` when the file is already gone locally
    (``local_sha`` None), ``clean`` when local still matches base, else ``conflict``.
    """
    if local_sha == result_sha:
        return "applied"
    if local_sha == base_sha:
        return "clean"
    return "conflict"


async def compute_handoff_diff(
    *,
    user_id: str,
    source_folder_id: str | None,
    source_conversation_id: str,
    base_snapshot_id: str,
    job_conversation_id: str,
    result_snapshot_id: str,
) -> list[FileChange]:
    """Read a finished handoff's base + result snapshots and diff them (P2e / e3).

    The base snapshot lives under the *source* conversation's storage key (the
    user's local files the cloud ran on); the result under the hidden *job*
    conversation's key (job workspaces are always ungrouped → ``folder_id=None``,
    matching how ``run_handoff_job`` snapshots the result). Raises
    ``SnapshotNotFound`` if either id is missing under its key.
    """
    provider = build_storage_provider()
    base_key = workspace_storage_key(
        user_id=user_id,
        folder_id=source_folder_id,
        conversation_id=source_conversation_id,
    )
    job_key = workspace_storage_key(
        user_id=user_id, folder_id=None, conversation_id=job_conversation_id
    )
    base_archive = await provider.read_snapshot(base_key, base_snapshot_id)
    result_archive = await provider.read_snapshot(job_key, result_snapshot_id)
    return diff_archives(base_archive, result_archive)
