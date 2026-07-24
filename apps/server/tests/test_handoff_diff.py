"""Unit tests for the handoff result diff engine (双模式工作区 P2e / e3).

No DB, desktop, object store, or LLM. Exercises the three seams that turn a
finished cloud run into a change set the desktop can apply:

* ``diff_archives`` — base vs result snapshot *zips* → per-file add / modify /
  delete (identical files omitted), with hashes + inline text (binary flagged).
* ``classify_three_way`` — the clean / already-applied / conflict verdict the
  desktop uses per file once it has hashed its current local copy.
* ``compute_handoff_diff`` — reads the base under the *source* key and the result
  under the *job* key, then diffs; the storage provider is faked with real zips so
  the key derivation and the end-to-end assembly are both asserted.
"""

import hashlib
import io
import zipfile

import pytest

from agentcore.storage.protocol import SnapshotNotFound
from agentcore.workspace import handoff_diff
from agentcore.workspace.handoff_diff import (
    classify_three_way,
    compute_handoff_diff,
    diff_archives,
)
from agentcore.workspace.locate import workspace_storage_key


def _zip(files: dict[str, bytes]) -> bytes:
    """Build a snapshot-shaped zip (POSIX names, file entries) from path → bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_diff_archives_detects_add_modify_delete():
    base = _zip({"a.py": b"old", "keep.py": b"same", "gone.py": b"bye"})
    result = _zip({"a.py": b"new", "keep.py": b"same", "added.py": b"hi"})

    changes = {c.path: c for c in diff_archives(base, result)}

    # Identical files contribute nothing.
    assert "keep.py" not in changes
    # Sorted, three real changes.
    assert [c.path for c in diff_archives(base, result)] == [
        "a.py",
        "added.py",
        "gone.py",
    ]

    mod = changes["a.py"]
    assert mod.change_type == "modified"
    assert mod.base_sha == _sha(b"old") and mod.result_sha == _sha(b"new")
    assert mod.content == "new" and mod.is_binary is False and mod.size_bytes == 3

    add = changes["added.py"]
    assert add.change_type == "added"
    assert add.base_sha is None and add.result_sha == _sha(b"hi")
    assert add.content == "hi" and add.size_bytes == 2

    rm = changes["gone.py"]
    assert rm.change_type == "deleted"
    assert rm.base_sha == _sha(b"bye") and rm.result_sha is None
    assert rm.content is None and rm.size_bytes == 0


def test_diff_archives_binary_result_has_no_inline_text():
    blob = b"\x89PNG\x00\x01\x02"  # NUL byte → binary
    changes = diff_archives(_zip({}), _zip({"img.png": blob}))

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "added"
    assert c.is_binary is True and c.content is None
    # A binary file still carries its hash + size so the client can fetch + verify it.
    assert c.result_sha == _sha(blob) and c.size_bytes == len(blob)


def test_diff_archives_identical_is_empty():
    same = _zip({"a.py": b"x", "b/c.txt": b"y"})
    assert diff_archives(same, same) == []


@pytest.mark.parametrize(
    ("base_sha", "result_sha", "local_sha", "expected"),
    [
        # modify: cloud changed B→R
        ("B", "R", "B", "clean"),  # local untouched since base
        ("B", "R", "R", "applied"),  # local already at the result
        ("B", "R", "L", "conflict"),  # local edited differently
        # add: file new in the result (base absent)
        (None, "R", None, "clean"),  # absent locally → clean add
        (None, "R", "R", "applied"),  # already created identically
        (None, "R", "X", "conflict"),  # user made a different file at the path
        # delete: file removed in the result (result absent)
        ("B", None, "B", "clean"),  # local still matches base → clean delete
        ("B", None, None, "applied"),  # already deleted locally
        ("B", None, "X", "conflict"),  # user edited it, cloud deleted it
    ],
)
def test_classify_three_way(base_sha, result_sha, local_sha, expected):
    assert (
        classify_three_way(base_sha=base_sha, result_sha=result_sha, local_sha=local_sha)
        == expected
    )


@pytest.mark.anyio
async def test_compute_handoff_diff_reads_source_and_job_keys(monkeypatch):
    base_key = workspace_storage_key(user_id="u1", folder_id=None, conversation_id="src")
    job_key = workspace_storage_key(user_id="u1", folder_id=None, conversation_id="job")
    base_zip = _zip({"main.py": b"v1"})
    result_zip = _zip({"main.py": b"v2", "new.py": b"+"})
    reads: list[tuple[str, str]] = []

    class _FakeProvider:
        async def read_snapshot(self, key: str, snapshot_id: str) -> bytes:
            reads.append((key, snapshot_id))
            if key == base_key and snapshot_id == "base-snap":
                return base_zip
            if key == job_key and snapshot_id == "result-snap":
                return result_zip
            raise SnapshotNotFound(f"{key}/{snapshot_id}")

    monkeypatch.setattr(handoff_diff, "build_storage_provider", lambda: _FakeProvider())

    changes = await compute_handoff_diff(
        user_id="u1",
        source_folder_id=None,
        source_conversation_id="src",
        base_snapshot_id="base-snap",
        job_conversation_id="job",
        result_snapshot_id="result-snap",
    )

    # Base is read under the source key, result under the (ungrouped) job key.
    assert (base_key, "base-snap") in reads
    assert (job_key, "result-snap") in reads
    assert {c.path: c.change_type for c in changes} == {
        "main.py": "modified",
        "new.py": "added",
    }


@pytest.mark.anyio
async def test_compute_handoff_diff_propagates_missing_snapshot(monkeypatch):
    class _MissingProvider:
        async def read_snapshot(self, key: str, snapshot_id: str) -> bytes:
            raise SnapshotNotFound(snapshot_id)

    monkeypatch.setattr(handoff_diff, "build_storage_provider", lambda: _MissingProvider())

    # A missing base/result id surfaces as SnapshotNotFound → the route maps it to 404.
    with pytest.raises(SnapshotNotFound):
        await compute_handoff_diff(
            user_id="u1",
            source_folder_id=None,
            source_conversation_id="src",
            base_snapshot_id="missing",
            job_conversation_id="job",
            result_snapshot_id="missing",
        )
