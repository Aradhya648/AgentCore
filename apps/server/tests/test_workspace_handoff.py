"""Tests for the local→cloud handoff snapshot (双模式工作区 P2e / e1).

``snapshot_local`` is the e1 leg: it asks the bound desktop (over the same
``WorkspaceChannel`` the file ops use) to pack its whole root into one archive,
unpacks it into a server-side staging dir, and hands that to the StorageProvider —
reusing the cloud snapshot machinery. These tests drive a fake "desktop" that
answers the ARCHIVE op with a real zip, and a fake provider that captures what got
staged, so we can assert the round trip end to end without a desktop or object
store. Covers: the archive is requested with ``ignore``, the staged dir contains
the unpacked files, the snapshot is a kept (``handoff:``-labeled) version, and a
zip-slip member is refused.
"""

import asyncio
import base64
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentcore.runtime.events import EventSink, SSEEvent
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.storage import SnapshotRef
from agentcore.workspace.channel import WorkspaceOp
from agentcore.workspace.handoff import snapshot_local
from agentcore.workspace.locate import LocalBinding, workspace_storage_key
from agentcore.workspace.protocol import WorkspaceIOError

pytestmark = pytest.mark.anyio

CONV = "conv-handoff-1"


def _zip_b64(files: dict[str, str]) -> str:
    """Base64 of a zip holding ``files`` (relpath → text), as the desktop returns."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _FakeProvider:
    """Captures the staged dir's contents so the unpack can be asserted."""

    def __init__(self) -> None:
        self.captured: dict | None = None

    async def snapshot(
        self, root: Path, storage_key: str, *, label: str | None = None
    ) -> SnapshotRef:
        files = {
            p.relative_to(root).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()
        }
        self.captured = {"key": storage_key, "label": label, "files": files}
        return SnapshotRef(
            snapshot_id="snap-1",
            label=label,
            created_at=datetime.now(UTC),
            size_bytes=42,
        )


async def _await_request(sink: EventSink) -> SSEEvent:
    """Return the op event the channel just emitted (yielding so the op runs)."""
    for _ in range(2000):
        if not sink._queue.empty():  # noqa: SLF001 - test-only inspection
            return sink._queue.get_nowait()
        await asyncio.sleep(0)
    raise AssertionError("no workspace_op_required event emitted")


async def _drive(monkeypatch, archive_value: dict) -> tuple[asyncio.Task, _FakeProvider]:
    """Start a handoff and answer its ARCHIVE op as the desktop would."""
    provider = _FakeProvider()
    monkeypatch.setattr("agentcore.workspace.handoff.build_storage_provider", lambda: provider)
    sink = EventSink()
    task = asyncio.create_task(
        snapshot_local(
            user_id="u1",
            folder_id=None,
            conversation_id=CONV,
            binding=LocalBinding(root_id="root-1", root_label="proj"),
            sink=sink,
        )
    )
    event = await _await_request(sink)
    assert event.payload["op"] == WorkspaceOp.ARCHIVE
    assert event.payload["args"] == {"ignore": True}
    assert event.payload["root_id"] == "root-1"
    settled = default_interaction_registry().resolve(
        event.payload["request_id"],
        {"ok": True, "value": archive_value},
        conversation_id=CONV,
    )
    assert settled
    return task, provider


async def test_snapshot_local_archives_and_snapshots(monkeypatch):
    archive = _zip_b64({"a.txt": "A", "sub/b.txt": "B"})
    task, provider = await _drive(
        monkeypatch,
        {"archive": archive, "file_count": 2, "total_bytes": 2, "truncated": False},
    )
    ref = await task

    assert ref.snapshot_id == "snap-1"
    assert provider.captured is not None
    # A handoff snapshot is a kept version (手动留版本 semantics): never auto-pruned.
    assert provider.captured["label"].startswith("handoff:")
    # The staged dir mirrors the cloud workspace storage key (same list/restore).
    assert provider.captured["key"] == workspace_storage_key(
        user_id="u1", folder_id=None, conversation_id=CONV
    )
    # The unpacked archive is exactly what the desktop sent.
    assert provider.captured["files"] == {"a.txt": "A", "sub/b.txt": "B"}


async def test_snapshot_local_rejects_zip_slip(monkeypatch):
    # A member escaping the staging dir must abort the whole extraction — never
    # write outside it — so a malformed/hostile desktop reply can't touch the host.
    archive = _zip_b64({"../evil.txt": "x"})
    task, provider = await _drive(
        monkeypatch,
        {"archive": archive, "file_count": 1, "total_bytes": 1, "truncated": False},
    )
    with pytest.raises(WorkspaceIOError):
        await task
    assert provider.captured is None  # nothing snapshotted on a rejected archive


async def test_snapshot_local_rejects_empty_archive(monkeypatch):
    # A desktop that returns no archive (e.g. an unbound/old client) fails cleanly.
    task, provider = await _drive(monkeypatch, {"archive": "", "file_count": 0, "total_bytes": 0})
    with pytest.raises(WorkspaceIOError):
        await task
    assert provider.captured is None


async def test_snapshot_local_passes_subpath_directory(monkeypatch):
    """ARCHIVE args must scope to LocalBinding.subpath (workspace-relative zip)."""
    provider = _FakeProvider()
    monkeypatch.setattr("agentcore.workspace.handoff.build_storage_provider", lambda: provider)
    sink = EventSink()
    task = asyncio.create_task(
        snapshot_local(
            user_id="u1",
            folder_id=None,
            conversation_id=CONV,
            binding=LocalBinding(
                root_id="root-1", root_label="proj", subpath="conversations/c1"
            ),
            sink=sink,
        )
    )
    event = await _await_request(sink)
    assert event.payload["op"] == WorkspaceOp.ARCHIVE
    assert event.payload["args"] == {
        "ignore": True,
        "directory": "conversations/c1",
    }
    settled = default_interaction_registry().resolve(
        event.payload["request_id"],
        {"ok": True, "value": {"archive": _zip_b64({"a.txt": "ok"})}},
        conversation_id=CONV,
    )
    assert settled
    await task


def test_handoff_routes_use_turn_routing_binding():
    """Handoff routes must share turn-routing binding (folder inherit / container).

    Guard against regressing to ``conv.local_root_id``-only resolution, which
    422s local project chats and container 裸聊 while the UI still offers 后台云端.
    """
    from pathlib import Path

    from agentcore.api.routes.conversations import handoff as handoff_routes

    src = Path(handoff_routes.__file__).read_text(encoding="utf-8")
    assert "resolve_local_binding" in src
    assert "resolve_conversation_local_binding" not in src
