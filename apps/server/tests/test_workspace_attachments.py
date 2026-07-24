"""Tests for attachment residency (附件驻留·决策⑤).

Hermetic: a ``ServerWorkspace`` rooted at ``tmp_path`` receives the writes, so the
real ``write`` + traversal guard run without touching the repo. Covers the happy
path (file written + workspace_path set), the pass-throughs (dirs, empty text),
name sanitization / dedup, the never-break-the-turn failure path, and the stored
metadata projection.
"""

from pathlib import Path

from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.attachments import (
    ATTACHMENTS_DIR,
    _safe_attachment_name,
    persist_attachments,
    to_stored_metadata,
)
from agentcore.workspace.protocol import WorkspaceIOError
from agentcore.workspace.server import ServerWorkspace


def _ws(root: Path) -> ServerWorkspace:
    return ServerWorkspace(root=root, sandbox=SubprocessSandbox())


async def test_persist_writes_file_and_sets_workspace_path(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws, [{"name": "notes.md", "path": "/local/notes.md", "text": "# hi\n"}]
    )

    assert out[0]["workspace_path"] == "attachments/notes.md"
    assert (tmp_path / "attachments" / "notes.md").read_text(encoding="utf-8") == "# hi\n"
    assert ws.dirty is True
    # The one-shot text is preserved on the enriched dict (for the context block).
    assert out[0]["text"] == "# hi\n"


async def test_persist_keeps_client_pre_resident_path(tmp_path: Path):
    """引用即驻留：客户端已写入 attachments/ 时跳过 rewrite，保留 workspace_path。"""
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "report.xlsx").write_bytes(b"PK\x03\x04")
    out = await persist_attachments(
        ws,
        [
            {
                "name": "report.xlsx",
                "path": "attachments/report.xlsx",
                "text": "",
                "binary": True,
                "workspace_path": "attachments/report.xlsx",
            }
        ],
    )
    assert out[0]["workspace_path"] == "attachments/report.xlsx"
    assert out[0]["binary"] is True
    # Must not overwrite binary with empty text write.
    assert (tmp_path / "attachments" / "report.xlsx").read_bytes() == b"PK\x03\x04"


async def test_persist_rejects_traversal_in_client_workspace_path(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws,
        [
            {
                "name": "x",
                "path": "x",
                "text": "",
                "binary": True,
                "workspace_path": "attachments/../evil.bin",
            }
        ],
    )
    assert "workspace_path" not in out[0] or out[0].get("workspace_path") is None


async def test_persist_rejects_workspace_path_outside_attachments(tmp_path: Path):
    """Client workspace_path must be a single segment under attachments/."""
    ws = _ws(tmp_path)
    cases = [
        "src/notes.md",
        "attachments/sub/nested.md",
        "attachments/",
        "..\\attachments\\x.md",
        "evil/attachments/x.md",
    ]
    for raw in cases:
        out = await persist_attachments(
            ws,
            [
                {
                    "name": "x",
                    "path": "x",
                    "text": "",
                    "binary": True,
                    "workspace_path": raw,
                }
            ],
        )
        assert out[0].get("workspace_path") is None, raw


async def test_persist_binary_without_workspace_path_stays_unresident(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws,
        [
            {
                "name": "report.xlsx",
                "path": "/local/report.xlsx",
                "text": "",
                "binary": True,
            }
        ],
    )
    assert out[0].get("workspace_path") is None
    assert not (tmp_path / ATTACHMENTS_DIR).exists()


def test_normalize_client_workspace_path():
    from agentcore.workspace.attachments import _normalize_client_workspace_path

    assert _normalize_client_workspace_path("attachments/a.xlsx") == "attachments/a.xlsx"
    assert _normalize_client_workspace_path("attachments\\b.txt") == "attachments/b.txt"
    assert _normalize_client_workspace_path("attachments/../evil") is None
    assert _normalize_client_workspace_path("attachments/foo/bar") is None
    assert _normalize_client_workspace_path("notes.md") is None
    assert _normalize_client_workspace_path(None) is None


async def test_persist_skips_directory(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws, [{"name": "src", "path": "/local/src", "text": "a.py\nb.py", "kind": "dir"}]
    )

    assert "workspace_path" not in out[0]
    assert not (tmp_path / ATTACHMENTS_DIR).exists()
    assert ws.dirty is False


async def test_persist_skips_empty_text(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws, [{"name": "empty.txt", "path": "/local/empty.txt", "text": "   "}]
    )
    assert "workspace_path" not in out[0]
    assert ws.dirty is False


async def test_persist_skips_conversation_reference(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws,
        [
            {
                "name": "讨论",
                "path": "对话",
                "text": "用户: hi\n\n助手: yo",
                "kind": "conversation",
                "conversation_id": "conv-1",
            }
        ],
    )
    # A conversation reference carries text but no file bytes — never resident.
    assert "workspace_path" not in out[0]
    assert not (tmp_path / ATTACHMENTS_DIR).exists()
    assert ws.dirty is False


async def test_persist_dedups_same_name(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(
        ws,
        [
            {"name": "report.txt", "path": "/a/report.txt", "text": "A"},
            {"name": "report.txt", "path": "/b/report.txt", "text": "B"},
        ],
    )
    assert out[0]["workspace_path"] == "attachments/report.txt"
    assert out[1]["workspace_path"] == "attachments/report (2).txt"
    assert (tmp_path / "attachments" / "report.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "attachments" / "report (2).txt").read_text(encoding="utf-8") == "B"


async def test_persist_sanitizes_traversal_name(tmp_path: Path):
    ws = _ws(tmp_path)
    out = await persist_attachments(ws, [{"name": "../../evil.sh", "path": "/x", "text": "rm -rf"}])
    # Directory parts are stripped: lands directly inside attachments/.
    assert out[0]["workspace_path"] == "attachments/evil.sh"
    assert (tmp_path / "attachments" / "evil.sh").exists()
    assert not (tmp_path.parent / "evil.sh").exists()


async def test_persist_none_returns_empty(tmp_path: Path):
    assert await persist_attachments(_ws(tmp_path), None) == []
    assert await persist_attachments(_ws(tmp_path), []) == []


class _FailingBackend:
    """Minimal backend whose write always fails (never-break-the-turn path)."""

    dirty = False

    async def write(self, path: str, content: str) -> int:
        raise WorkspaceIOError("disk full")


async def test_persist_write_failure_is_skipped():
    out = await persist_attachments(
        _FailingBackend(), [{"name": "x.txt", "path": "/x.txt", "text": "data"}]
    )
    # The turn proceeds: the attachment is returned un-resident, not raised.
    assert out[0].get("workspace_path") is None


def test_to_stored_metadata_drops_text_keeps_path():
    stored = to_stored_metadata(
        [
            {
                "name": "a.py",
                "path": "/local/a.py",
                "text": "secret source",
                "truncated": True,
                "kind": "file",
                "workspace_path": "attachments/a.py",
            }
        ]
    )
    assert stored == [
        {
            "name": "a.py",
            "path": "/local/a.py",
            "truncated": True,
            "kind": "file",
            "workspace_path": "attachments/a.py",
            "conversation_id": None,
            "binary": False,
        }
    ]
    assert "text" not in stored[0]


def test_to_stored_metadata_defaults_for_unpersisted():
    stored = to_stored_metadata([{"name": "d", "path": "/d", "kind": "dir"}])
    assert stored[0]["workspace_path"] is None
    assert stored[0]["truncated"] is False


def test_to_stored_metadata_keeps_conversation_id():
    stored = to_stored_metadata(
        [
            {
                "name": "讨论",
                "path": "对话",
                "text": "用户: hi",
                "kind": "conversation",
                "conversation_id": "conv-1",
            }
        ]
    )
    assert stored[0]["kind"] == "conversation"
    assert stored[0]["conversation_id"] == "conv-1"
    # A conversation reference is never written to disk → no workspace_path.
    assert stored[0]["workspace_path"] is None
    # The one-shot text is still dropped from stored metadata.
    assert "text" not in stored[0]


def test_safe_attachment_name():
    assert _safe_attachment_name("foo.py") == "foo.py"
    assert _safe_attachment_name("src/sub/foo.py") == "foo.py"
    assert _safe_attachment_name("..\\..\\evil.txt") == "evil.txt"
    assert _safe_attachment_name("") == "attachment"
    assert _safe_attachment_name("...") == "attachment"
