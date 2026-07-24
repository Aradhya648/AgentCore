"""Tests for ServerWorkspace — the cloud-mode WorkspaceBackend.

Hermetic: every test builds a throwaway tree under ``tmp_path`` and points the
backend's root at it, so the traversal guard, file I/O, and the typed error
contract are exercised without touching the real repo. The ``execute`` test also
pins the cwd fix: code runs in the workspace root and can read workspace files.
"""

import contextlib
import os
import time
from pathlib import Path

import pytest

from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.protocol import (
    AlreadyExists,
    AmbiguousMatch,
    GrepQuery,
    NoMatch,
    NotADirectory,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
    WorkspaceIOError,
)
from agentcore.workspace.server import ServerWorkspace


def _ws(root: Path) -> ServerWorkspace:
    return ServerWorkspace(root=root, sandbox=SubprocessSandbox())


# --- read ---


async def test_read_returns_content(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    assert await _ws(tmp_path).read("a.txt") == "hello"


async def test_read_missing_raises_path_not_found(tmp_path: Path):
    with pytest.raises(PathNotFound):
        await _ws(tmp_path).read("nope.txt")


async def test_read_directory_raises_not_a_file(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    with pytest.raises(NotAFile):
        await _ws(tmp_path).read("sub")


async def test_read_escape_raises_outside_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(OutsideWorkspace):
        await _ws(ws).read("../secret.txt")


# --- absolute root-label path normalization (单一接缝: /workspace/... rescue) ---


async def test_absolute_root_label_path_write_and_read(tmp_path: Path):
    # A worker passing the industry-habit absolute path (/workspace/...) used to hit
    # OutsideWorkspace and waste retries; it now resolves to the in-tree relative file.
    ws = _ws(tmp_path)
    written = await ws.write("/workspace/research/x.md", "hi")
    assert written == 2
    assert (tmp_path / "research" / "x.md").read_text(encoding="utf-8") == "hi"
    assert await ws.read("/workspace/research/x.md") == "hi"


async def test_absolute_root_label_root_points_at_workspace_root(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    entries = {e.path for e in await _ws(tmp_path).list("/workspace", "*")}
    assert "a.txt" in entries


async def test_absolute_non_label_path_still_outside(tmp_path: Path):
    # A different absolute root is NOT normalized — it stays rejected.
    with pytest.raises(OutsideWorkspace):
        await _ws(tmp_path).read("/etc/passwd")


async def test_absolute_root_label_traversal_still_outside(tmp_path: Path):
    # Normalization strips the label segment but never defuses ``..``.
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (tmp_path / "secret.txt").write_text("top", encoding="utf-8")
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).read("/workspace/../secret.txt")
    assert (tmp_path / "secret.txt").read_text(encoding="utf-8") == "top"


async def test_relative_paths_unchanged_under_default_label(tmp_path: Path):
    # Ordinary relative paths behave exactly as before.
    ws = _ws(tmp_path)
    await ws.write("notes/report.md", "body")
    assert (tmp_path / "notes" / "report.md").read_text(encoding="utf-8") == "body"


async def test_custom_root_label_normalizes_by_that_label(tmp_path: Path):
    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox(), root_label="proj")
    await ws.write("/proj/out.md", "ok")
    assert (tmp_path / "out.md").read_text(encoding="utf-8") == "ok"
    # the default "workspace" label is not honored when the backend uses "proj"
    with pytest.raises(OutsideWorkspace):
        await ws.read("/workspace/out.md")


# --- write ---


async def test_write_creates_parents_and_returns_count(tmp_path: Path):
    written = await _ws(tmp_path).write("nested/dir/out.txt", "abcd")
    assert written == 4
    assert (tmp_path / "nested" / "dir" / "out.txt").read_text(encoding="utf-8") == "abcd"


async def test_write_escape_raises_outside_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(OutsideWorkspace):
        await _ws(ws).write("../evil.txt", "x")


async def test_append_creates_file_and_returns_count(tmp_path: Path):
    written = await _ws(tmp_path).append("draft.md", "hello")
    assert written == 5
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "hello"


async def test_append_extends_existing_file(tmp_path: Path):
    (tmp_path / "draft.md").write_text("hi", encoding="utf-8")
    written = await _ws(tmp_path).append("draft.md", " there")
    assert written == 6
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "hi there"


async def test_append_on_directory_raises_not_a_file(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    with pytest.raises(NotAFile):
        await _ws(tmp_path).append("pkg", "x")


# --- list ---


async def test_list_marks_dirs_and_files(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    (tmp_path / "d").mkdir()
    entries = {e.path: e.is_dir for e in await _ws(tmp_path).list(".", "*")}
    assert entries.get("f.txt") is False
    assert entries.get("d") is True


async def test_list_on_file_raises_not_a_directory(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectory):
        await _ws(tmp_path).list("f.txt", "*")


# --- replace ---


async def test_replace_single_reports_count_and_line(tmp_path: Path):
    (tmp_path / "f.txt").write_text("l1\nFOO\nl3\n", encoding="utf-8")
    outcome = await _ws(tmp_path).replace("f.txt", "FOO", "BAR", all_=False)
    assert outcome.count == 1
    assert outcome.first_line == 2
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "l1\nBAR\nl3\n"


async def test_replace_all_counts_every_span(tmp_path: Path):
    (tmp_path / "f.txt").write_text("aXaXa", encoding="utf-8")
    outcome = await _ws(tmp_path).replace("f.txt", "a", "b", all_=True)
    assert outcome.count == 3
    assert outcome.first_line is None
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "bXbXb"


async def test_replace_no_match_raises(tmp_path: Path):
    (tmp_path / "f.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(NoMatch):
        await _ws(tmp_path).replace("f.txt", "zzz", "q", all_=False)


async def test_replace_ambiguous_raises_with_count(tmp_path: Path):
    (tmp_path / "f.txt").write_text("aXaXa", encoding="utf-8")
    with pytest.raises(AmbiguousMatch) as exc:
        await _ws(tmp_path).replace("f.txt", "a", "b", all_=False)
    assert exc.value.count == 3


async def test_replace_binary_raises_not_utf8(tmp_path: Path):
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(NotUTF8):
        await _ws(tmp_path).replace("blob.bin", "x", "y", all_=False)


async def test_replace_missing_raises_path_not_found(tmp_path: Path):
    with pytest.raises(PathNotFound):
        await _ws(tmp_path).replace("nope.txt", "x", "y", all_=False)


# --- execute (the cwd fix) ---


async def test_execute_runs_in_workspace_so_code_sees_files(tmp_path: Path):
    """Code runs with cwd = workspace root, so a relative open() finds the file
    the file tools wrote — the bug where code_execute ran in a throwaway tempdir."""
    (tmp_path / "data.txt").write_text("hello-from-workspace", encoding="utf-8")
    result = await _ws(tmp_path).execute(
        ExecutionRequest(
            code="print(open('data.txt').read())",
            language="python",
            timeout_seconds=15,
        )
    )
    assert result.success
    assert "hello-from-workspace" in result.stdout


# --- dirty tracking (drives the post-turn auto-snapshot, 决策⑥) ---


async def test_starts_clean(tmp_path: Path):
    assert _ws(tmp_path).dirty is False


async def test_read_only_ops_do_not_dirty(tmp_path: Path):
    (tmp_path / "f.txt").write_text("hello", encoding="utf-8")
    ws = _ws(tmp_path)
    await ws.read("f.txt")
    await ws.list(".", "*")
    await ws.grep(GrepQuery(pattern="hello"))
    assert ws.dirty is False


# --- grep thread offload (ReDoS / event-loop safety) ---


async def test_grep_wait_for_timeout_fires_while_scan_runs(tmp_path: Path, monkeypatch):
    """``asyncio.wait_for`` must be able to expire while grep is still scanning.

    Before the to_thread offload, sync ``re`` / ``os.walk`` held the event loop so
    the timeout could not fire until the whole scan finished.
    """
    import asyncio

    (tmp_path / "f.txt").write_text("hello\n", encoding="utf-8")
    ws = _ws(tmp_path)
    real = ServerWorkspace._grep_sync

    def slow(self: ServerWorkspace, base: Path, query: GrepQuery, logical_dir: str):
        time.sleep(1.0)
        return real(self, base, query, logical_dir)

    monkeypatch.setattr(ServerWorkspace, "_grep_sync", slow)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.05)

    task = asyncio.create_task(ticker())
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(ws.grep(GrepQuery(pattern="hello")), timeout=0.15)
        elapsed = time.monotonic() - t0
        # Timeout must surface promptly (not after the 1s sleep), and the loop
        # must have kept scheduling the ticker while wait_for was pending.
        assert elapsed < 0.6
        assert ticks >= 2
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_grep_result_shape_unchanged_after_offload(tmp_path: Path):
    """Thread offload must not change GrepResult fields / hit formatting inputs."""
    (tmp_path / "a.py").write_text("foo = 1\nbar = 2\nfoo again\n", encoding="utf-8")
    result = await _ws(tmp_path).grep(GrepQuery(pattern="foo", max_results=10))
    assert result.total_matches == 2
    assert result.truncated is False
    assert [(h.path, h.line_no, h.text) for h in result.hits] == [
        ("a.py", 1, "foo = 1"),
        ("a.py", 3, "foo again"),
    ]
    assert result.file_counts == [("a.py", 2)]


async def test_write_marks_dirty(tmp_path: Path):
    ws = _ws(tmp_path)
    await ws.write("out.txt", "x")
    assert ws.dirty is True


async def test_replace_marks_dirty(tmp_path: Path):
    (tmp_path / "f.txt").write_text("FOO", encoding="utf-8")
    ws = _ws(tmp_path)
    await ws.replace("f.txt", "FOO", "BAR", all_=False)
    assert ws.dirty is True


async def test_failed_write_does_not_dirty(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    ws = _ws(ws_root)
    with pytest.raises(OutsideWorkspace):
        await ws.write("../escape.txt", "x")
    assert ws.dirty is False


async def test_execute_marks_dirty(tmp_path: Path):
    ws = _ws(tmp_path)
    await ws.execute(ExecutionRequest(code="print('hi')", language="python", timeout_seconds=15))
    assert ws.dirty is True


# --- binary I/O (file upload / download) ---


async def test_write_then_read_bytes_roundtrip(tmp_path: Path):
    blob = bytes(range(256))  # non-UTF-8 bytes
    ws = _ws(tmp_path)
    written = await ws.write_bytes("nested/blob.bin", blob)
    assert written == 256
    assert await ws.read_bytes("nested/blob.bin") == blob


async def test_write_bytes_marks_dirty(tmp_path: Path):
    ws = _ws(tmp_path)
    await ws.write_bytes("f.bin", b"\x00\x01")
    assert ws.dirty is True


async def test_read_bytes_missing_raises_path_not_found(tmp_path: Path):
    with pytest.raises(PathNotFound):
        await _ws(tmp_path).read_bytes("nope.bin")


async def test_read_bytes_directory_raises_not_a_file(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    with pytest.raises(NotAFile):
        await _ws(tmp_path).read_bytes("sub")


async def test_read_bytes_escape_raises_outside_workspace(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (tmp_path / "secret.bin").write_bytes(b"x")
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).read_bytes("../secret.bin")


async def test_write_bytes_escape_raises_outside_workspace(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).write_bytes("../evil.bin", b"x")


# --- delete / move (rename) ---


async def test_delete_removes_file(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    ws = _ws(tmp_path)
    await ws.delete("f.txt")
    assert not (tmp_path / "f.txt").exists()
    assert ws.dirty is True
    trash = tmp_path / ".agentcore" / "trash"
    assert trash.is_dir()
    entries = list(trash.iterdir())
    assert len(entries) == 1
    assert (entries[0] / "content").read_text(encoding="utf-8") == "x"


async def test_delete_removes_directory_recursively(tmp_path: Path):
    (tmp_path / "d" / "sub").mkdir(parents=True)
    (tmp_path / "d" / "sub" / "f.txt").write_text("x", encoding="utf-8")
    await _ws(tmp_path).delete("d")
    assert not (tmp_path / "d").exists()
    assert (tmp_path / ".agentcore" / "trash").is_dir()


async def test_delete_permanent_hard_removes(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    await _ws(tmp_path).delete("f.txt", permanent=True)
    assert not (tmp_path / "f.txt").exists()
    trash = tmp_path / ".agentcore" / "trash"
    assert not trash.exists() or not any(trash.iterdir())


async def test_delete_missing_raises_path_not_found(tmp_path: Path):
    with pytest.raises(PathNotFound):
        await _ws(tmp_path).delete("nope.txt")


async def test_delete_root_raises_outside_workspace(tmp_path: Path):
    # Refuse to nuke the workspace itself, however the root is addressed.
    with pytest.raises(OutsideWorkspace):
        await _ws(tmp_path).delete(".")


async def test_delete_escape_raises_outside_workspace(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).delete("../secret.txt")
    assert (tmp_path / "secret.txt").exists()


async def test_failed_delete_does_not_dirty(tmp_path: Path):
    ws = _ws(tmp_path)
    with pytest.raises(PathNotFound):
        await ws.delete("nope.txt")
    assert ws.dirty is False


async def test_copy_file_and_tree(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\xff")
    ws = _ws(tmp_path)
    await ws.copy("a.txt", "nested/b.txt")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (tmp_path / "nested" / "b.txt").read_text(encoding="utf-8") == "hello"
    await ws.copy("bin.dat", "nested/bin.dat")
    assert (tmp_path / "nested" / "bin.dat").read_bytes() == b"\x00\x01\xff"

    (tmp_path / "tree" / "sub").mkdir(parents=True)
    (tmp_path / "tree" / "sub" / "c.txt").write_text("c", encoding="utf-8")
    await ws.copy("tree", "tree2")
    assert (tmp_path / "tree2" / "sub" / "c.txt").read_text(encoding="utf-8") == "c"


async def test_copy_refuses_overwrite_and_into_self(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    ws = _ws(tmp_path)
    with pytest.raises(AlreadyExists):
        await ws.copy("a.txt", "b.txt")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f.txt").write_text("f", encoding="utf-8")
    with pytest.raises(WorkspaceIOError):
        await ws.copy("d", "d/nested")


async def test_move_renames_file(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    ws = _ws(tmp_path)
    await ws.move("a.txt", "b.txt")
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "hello"
    assert ws.dirty is True


async def test_move_creates_destination_parents(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    await _ws(tmp_path).move("a.txt", "nested/dir/b.txt")
    assert (tmp_path / "nested" / "dir" / "b.txt").read_text(encoding="utf-8") == "hello"


async def test_move_directory(tmp_path: Path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f.txt").write_text("x", encoding="utf-8")
    await _ws(tmp_path).move("d", "renamed")
    assert (tmp_path / "renamed" / "f.txt").read_text(encoding="utf-8") == "x"


async def test_move_missing_source_raises_path_not_found(tmp_path: Path):
    with pytest.raises(PathNotFound):
        await _ws(tmp_path).move("nope.txt", "b.txt")


async def test_move_onto_existing_raises_already_exists(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    ws = _ws(tmp_path)
    with pytest.raises(AlreadyExists):
        await ws.move("a.txt", "b.txt")
    # Both untouched, and the failed move left the workspace clean.
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a"
    assert ws.dirty is False


async def test_move_escape_source_raises_outside_workspace(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).move("../secret.txt", "stolen.txt")


async def test_move_escape_destination_raises_outside_workspace(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).move("a.txt", "../escape.txt")


# --- mkdir (new folder) ---


async def test_mkdir_creates_directory(tmp_path: Path):
    ws = _ws(tmp_path)
    await ws.mkdir("newdir")
    assert (tmp_path / "newdir").is_dir()
    assert ws.dirty is True


async def test_mkdir_creates_parents(tmp_path: Path):
    await _ws(tmp_path).mkdir("a/b/c")
    assert (tmp_path / "a" / "b" / "c").is_dir()


async def test_mkdir_existing_raises_already_exists(tmp_path: Path):
    (tmp_path / "d").mkdir()
    ws = _ws(tmp_path)
    with pytest.raises(AlreadyExists):
        await ws.mkdir("d")
    assert ws.dirty is False


async def test_mkdir_root_raises_outside_workspace(tmp_path: Path):
    with pytest.raises(OutsideWorkspace):
        await _ws(tmp_path).mkdir(".")


async def test_mkdir_escape_raises_outside_workspace(tmp_path: Path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    with pytest.raises(OutsideWorkspace):
        await _ws(ws_root).mkdir("../escape")
    assert not (tmp_path / "escape").exists()


# --- read_for_edit (full text + mtime baseline + eol) ---


async def test_read_for_edit_returns_text_mtime_and_eol(tmp_path: Path):
    # write_bytes (not write_text): on Windows write_text would translate \n→\r\n and
    # flip the detected eol; we want a genuine LF fixture here.
    (tmp_path / "a.md").write_bytes("# 标题\n正文".encode())
    text, mtime_ms, eol = await _ws(tmp_path).read_for_edit("a.md")
    assert text == "# 标题\n正文"
    assert eol == "lf"
    assert mtime_ms > 0


async def test_read_for_edit_normalizes_crlf_and_reports_eol(tmp_path: Path):
    # CRLF is normalized to \n for the editor; eol="crlf" so write restores it.
    (tmp_path / "win.md").write_bytes(b"a\r\nb\r\n")
    text, _mtime, eol = await _ws(tmp_path).read_for_edit("win.md")
    assert text == "a\nb\n"
    assert eol == "crlf"


async def test_read_for_edit_binary_raises_not_utf8(tmp_path: Path):
    (tmp_path / "bin").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(NotUTF8):
        await _ws(tmp_path).read_for_edit("bin")


async def test_read_for_edit_missing_raises_path_not_found(tmp_path: Path):
    with pytest.raises(PathNotFound):
        await _ws(tmp_path).read_for_edit("nope.md")


# --- write_text_cas (mtime conditional write) ---


async def test_write_text_cas_new_file_succeeds(tmp_path: Path):
    ok, mtime_ms = await _ws(tmp_path).write_text_cas(
        "new.md", "hello", baseline_mtime_ms=0, eol="lf"
    )
    assert ok is True
    assert mtime_ms > 0
    assert (tmp_path / "new.md").read_text(encoding="utf-8") == "hello"


async def test_write_text_cas_new_file_conflict_when_exists(tmp_path: Path):
    (tmp_path / "x.md").write_text("old", encoding="utf-8")
    ok, disk_ms = await _ws(tmp_path).write_text_cas("x.md", "new", baseline_mtime_ms=0, eol="lf")
    assert ok is False  # baseline 0 = "new file", but it already exists
    assert disk_ms > 0
    assert (tmp_path / "x.md").read_text(encoding="utf-8") == "old"  # not clobbered


async def test_write_text_cas_matching_baseline_overwrites(tmp_path: Path):
    ws = _ws(tmp_path)
    _text, baseline, _eol = await _seed_and_read(ws, tmp_path, "doc.md", "v1")
    ok, new_ms = await ws.write_text_cas("doc.md", "v2", baseline_mtime_ms=baseline, eol="lf")
    assert ok is True
    assert new_ms >= baseline
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "v2"


async def test_write_text_cas_stale_baseline_conflicts(tmp_path: Path):
    # Disk changed since the editor read it → conflict carrying the current mtime,
    # and the file is left untouched (never blind-clobbered).
    ok, disk_ms = await _ws(tmp_path).write_text_cas(
        "doc.md", "mine", baseline_mtime_ms=123, eol="lf"
    )
    # baseline 123 but file doesn't exist → conflict (deleted/never-there under us)
    assert ok is False
    assert disk_ms == 0


async def test_write_text_cas_detects_external_change(tmp_path: Path):
    ws = _ws(tmp_path)
    _t, baseline, _e = await _seed_and_read(ws, tmp_path, "doc.md", "v1")
    # Simulate an Agent writing the file after the editor's baseline read: bump the
    # mtime forward so the CAS sees a changed disk and refuses to clobber.
    later = (baseline + 5000) / 1000
    (tmp_path / "doc.md").write_text("agent-edit", encoding="utf-8")
    os.utime(tmp_path / "doc.md", (later, later))
    ok, disk_ms = await ws.write_text_cas(
        "doc.md", "user-edit", baseline_mtime_ms=baseline, eol="lf"
    )
    assert ok is False
    assert disk_ms != baseline
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "agent-edit"


async def test_write_text_cas_restores_crlf(tmp_path: Path):
    ok, _ms = await _ws(tmp_path).write_text_cas("win.md", "a\nb", baseline_mtime_ms=0, eol="crlf")
    assert ok is True
    assert (tmp_path / "win.md").read_bytes() == b"a\r\nb"


async def _seed_and_read(
    ws: ServerWorkspace, root: Path, name: str, content: str
) -> tuple[str, int, str]:
    """Write a file directly then read its edit baseline (text, mtime_ms, eol)."""
    (root / name).write_text(content, encoding="utf-8")
    return await ws.read_for_edit(name)
