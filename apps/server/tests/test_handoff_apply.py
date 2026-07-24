"""Unit tests for the handoff result apply (双模式工作区 P2e / e3).

No DB, desktop, object store, or LLM. ``apply_handoff`` is driven against a fake
``WorkspaceBackend`` (records WRITE_BYTES / DELETE instead of touching a disk) and a
fake storage provider that returns real base + result zips, so the whole decision
table is asserted: a ``local`` decision is skipped; a ``cloud`` decision is applied
when clean, skipped when already-applied, refused when it conflicts (unless forced),
and surfaced as an error for an unknown path or a backend write failure. Result bytes
(binary included) are written verbatim.
"""

import hashlib
import io
import zipfile

import pytest

from agentcore.storage.protocol import SnapshotNotFound
from agentcore.workspace import handoff_apply
from agentcore.workspace.handoff_apply import ApplySelection, apply_handoff
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.protocol import WorkspaceIOError

pytestmark = pytest.mark.anyio

_BASE_KEY = workspace_storage_key(user_id="u1", folder_id=None, conversation_id="src")
_JOB_KEY = workspace_storage_key(user_id="u1", folder_id=None, conversation_id="job")

# A base → result the tests share: one modify, one delete, one add, one binary add,
# plus a modify whose local copy already matches the result.
_BASE = {"mod.py": b"base", "del.py": b"old", "already.py": b"baseA"}
_RESULT = {
    "mod.py": b"cloud",
    "already.py": b"cloudA",
    "add.py": b"new",
    "img.bin": b"\x00\x01\x02",
}


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FakeBackend:
    location = "local"

    def __init__(self, fail_paths: set[str] | None = None) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.deletes: list[str] = []
        self._fail = fail_paths or set()

    async def write_bytes(self, path: str, data: bytes) -> int:
        if path in self._fail:
            raise WorkspaceIOError("write failed")
        self.writes.append((path, data))
        return len(data)

    async def delete(self, path: str) -> None:
        if path in self._fail:
            raise WorkspaceIOError("delete failed")
        self.deletes.append(path)


class _FakeProvider:
    async def read_snapshot(self, key: str, snapshot_id: str) -> bytes:
        if key == _BASE_KEY and snapshot_id == "base":
            return _zip(_BASE)
        if key == _JOB_KEY and snapshot_id == "res":
            return _zip(_RESULT)
        raise SnapshotNotFound(f"{key}/{snapshot_id}")


async def _apply(monkeypatch, selections, *, backend=None) -> tuple[list, _FakeBackend]:
    backend = backend or _FakeBackend()
    monkeypatch.setattr(handoff_apply, "build_storage_provider", lambda: _FakeProvider())
    outcomes = await apply_handoff(
        backend=backend,
        user_id="u1",
        source_folder_id=None,
        source_conversation_id="src",
        base_snapshot_id="base",
        job_conversation_id="job",
        result_snapshot_id="res",
        selections=selections,
    )
    return outcomes, backend


async def test_apply_clean_changes_write_and_delete(monkeypatch):
    outcomes, backend = await _apply(
        monkeypatch,
        [
            ApplySelection(path="mod.py", decision="cloud", local_sha=_sha(b"base")),
            ApplySelection(path="del.py", decision="cloud", local_sha=_sha(b"old")),
            ApplySelection(path="add.py", decision="cloud", local_sha=None),
        ],
    )

    status = {o.path: o.status for o in outcomes}
    assert status == {"mod.py": "applied", "del.py": "applied", "add.py": "applied"}
    # The modify + add write the *result* bytes verbatim; the delete removes the path.
    assert ("mod.py", b"cloud") in backend.writes
    assert ("add.py", b"new") in backend.writes
    assert backend.deletes == ["del.py"]


async def test_apply_binary_result_written_verbatim(monkeypatch):
    outcomes, backend = await _apply(
        monkeypatch,
        [ApplySelection(path="img.bin", decision="cloud", local_sha=None)],
    )
    assert outcomes[0].status == "applied"
    assert backend.writes == [("img.bin", b"\x00\x01\x02")]


async def test_apply_keep_local_is_skipped_without_write(monkeypatch):
    outcomes, backend = await _apply(
        monkeypatch,
        [ApplySelection(path="mod.py", decision="local", local_sha=_sha(b"base"))],
    )
    assert outcomes[0].status == "skipped"
    assert backend.writes == [] and backend.deletes == []


async def test_apply_already_applied_is_skipped(monkeypatch):
    # Local already equals the result → no-op (idempotent re-apply).
    outcomes, backend = await _apply(
        monkeypatch,
        [ApplySelection(path="already.py", decision="cloud", local_sha=_sha(b"cloudA"))],
    )
    assert outcomes[0].status == "skipped"
    assert backend.writes == []


async def test_apply_conflict_is_refused_then_forced(monkeypatch):
    # Local diverged from base AND from result → conflict, refused, nothing written.
    outcomes, backend = await _apply(
        monkeypatch,
        [ApplySelection(path="mod.py", decision="cloud", local_sha=_sha(b"local-edit"))],
    )
    assert outcomes[0].status == "conflict"
    assert backend.writes == []

    # The same selection with force applies the cloud version over the conflict.
    outcomes, backend = await _apply(
        monkeypatch,
        [
            ApplySelection(
                path="mod.py", decision="cloud", local_sha=_sha(b"local-edit"), force=True
            )
        ],
    )
    assert outcomes[0].status == "applied"
    assert backend.writes == [("mod.py", b"cloud")]


async def test_apply_unknown_path_is_error(monkeypatch):
    outcomes, backend = await _apply(
        monkeypatch,
        [ApplySelection(path="not-in-result.py", decision="cloud", local_sha=None)],
    )
    assert outcomes[0].status == "error"
    assert backend.writes == [] and backend.deletes == []


async def test_apply_backend_failure_is_error_and_continues(monkeypatch):
    # A write failure on one file is captured as error and never aborts the rest.
    backend = _FakeBackend(fail_paths={"mod.py"})
    outcomes, backend = await _apply(
        monkeypatch,
        [
            ApplySelection(path="mod.py", decision="cloud", local_sha=_sha(b"base")),
            ApplySelection(path="add.py", decision="cloud", local_sha=None),
        ],
        backend=backend,
    )
    status = {o.path: o.status for o in outcomes}
    assert status == {"mod.py": "error", "add.py": "applied"}
    assert ("add.py", b"new") in backend.writes


async def test_apply_missing_snapshot_propagates(monkeypatch):
    monkeypatch.setattr(handoff_apply, "build_storage_provider", lambda: _FakeProvider())
    with pytest.raises(SnapshotNotFound):
        await apply_handoff(
            backend=_FakeBackend(),
            user_id="u1",
            source_folder_id=None,
            source_conversation_id="src",
            base_snapshot_id="MISSING",
            job_conversation_id="job",
            result_snapshot_id="res",
            selections=[ApplySelection(path="mod.py", decision="cloud", local_sha=None)],
        )
