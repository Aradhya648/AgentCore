"""Tests for the str_replace tool (precise, byte-faithful, atomic file edit).

Hermetic: every test edits a throwaway file under ``tmp_path`` and reads the
bytes back to assert the on-disk result, including line-ending fidelity.
"""

from pathlib import Path

from agentcore.tools.builtin.file_ops import StrReplaceTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
    )


# --- validation / failure paths ---


async def test_requires_old_string(tmp_path: Path):
    (tmp_path / "f.txt").write_text("hi", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "f.txt", "old_string": "", "new_string": "x"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "old_string 不能为空" in result.error


async def test_rejects_identical_strings(tmp_path: Path):
    (tmp_path / "f.txt").write_text("hi", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "f.txt", "old_string": "hi", "new_string": "hi"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "相同" in result.error


async def test_rejects_path_outside_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "../secret.txt", "old_string": "secret", "new_string": "x"},
        _ctx(ws),
    )
    assert result.success is False
    assert "超出了工作区范围" in result.error
    # the out-of-tree file must be untouched
    assert (tmp_path / "secret.txt").read_text(encoding="utf-8") == "top secret"


async def test_file_not_found(tmp_path: Path):
    result = await StrReplaceTool().execute(
        {"path": "nope.txt", "old_string": "a", "new_string": "b"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "文件不存在" in result.error


async def test_rejects_directory(tmp_path: Path):
    (tmp_path / "d").mkdir()
    result = await StrReplaceTool().execute(
        {"path": "d", "old_string": "a", "new_string": "b"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "不是文件" in result.error


async def test_rejects_binary_file(tmp_path: Path):
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    result = await StrReplaceTool().execute(
        {"path": "blob.bin", "old_string": "a", "new_string": "b"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "非 UTF-8" in result.error


async def test_old_string_not_found(tmp_path: Path):
    (tmp_path / "f.txt").write_text("hello world\nsecond line\n", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "f.txt", "old_string": "xyz", "new_string": "b"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "找不到" in result.error
    # 阶段3：失败回执必须带回磁盘片段（真源），不能只报「找不到」。
    assert "磁盘原文" in (result.error or "")
    assert "hello world" in (result.error or "")
    assert "勿残缺骨架交差" in (result.error or "")
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "hello world\nsecond line\n"


async def test_no_match_includes_fuzzy_near_miss(tmp_path: Path):
    """Near-miss old_string still gets disk candidates marked non-exact."""
    (tmp_path / "app.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    result = await StrReplaceTool().execute(
        {
            "path": "app.py",
            "old_string": "return a - b;",  # trailing ; drift
            "new_string": "return a + b",
        },
        _ctx(tmp_path),
    )
    assert result.success is False
    assert "找不到" in (result.error or "")
    assert "非精确" in (result.error or "")
    assert "return a - b" in (result.error or "")


async def test_non_unique_without_replace_all_fails(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x = 1\nx = 2\n", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "f.txt", "old_string": "x", "new_string": "y"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "不唯一" in result.error
    assert "2 处" in result.error
    assert "精确命中" in (result.error or "")
    assert "x = 1" in (result.error or "")
    # nothing changed
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "x = 1\nx = 2\n"


# --- core edit behavior ---


async def test_single_unique_replacement(tmp_path: Path):
    f = tmp_path / "app.py"
    f.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "app.py", "old_string": "return a - b", "new_string": "return a + b"},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert result.metadata["replacements"] == 1
    assert "约第 2 行" in result.output
    # 回执回显改动落点上下文（所改即所见），让 worker 当轮确认替换落对没、免掉回读自检那一轮。
    assert "return a + b" in result.output
    assert "改动落点" in result.output
    assert f.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


async def test_replace_all(tmp_path: Path):
    f = tmp_path / "f.txt"
    f.write_text("a\na\na\n", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "f.txt", "old_string": "a", "new_string": "b", "replace_all": True},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert result.metadata["replacements"] == 3
    assert f.read_text(encoding="utf-8") == "b\nb\nb\n"


async def test_multiline_old_string(tmp_path: Path):
    f = tmp_path / "f.txt"
    # write_bytes (not write_text) so the test controls line endings exactly —
    # on Windows write_text would translate \n to \r\n and the LF old_string
    # below would (correctly) no longer match.
    f.write_bytes(b"line1\nline2\nline3\n")
    result = await StrReplaceTool().execute(
        {
            "path": "f.txt",
            "old_string": "line1\nline2\n",
            "new_string": "lineA\n",
        },
        _ctx(tmp_path),
    )
    assert result.success is True
    assert f.read_bytes() == b"lineA\nline3\n"


async def test_preserves_crlf_line_endings(tmp_path: Path):
    """Byte fidelity: a CRLF file must stay CRLF after an edit (no translation)."""
    f = tmp_path / "win.txt"
    f.write_bytes(b"alpha\r\nTARGET\r\nomega\r\n")
    result = await StrReplaceTool().execute(
        {"path": "win.txt", "old_string": "TARGET", "new_string": "DONE"},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert f.read_bytes() == b"alpha\r\nDONE\r\nomega\r\n"


async def test_crlf_file_accepts_lf_multiline_old_string(tmp_path: Path):
    """CRLF on disk + LF multiline old_string: normalize fallback, write-back CRLF."""
    f = tmp_path / "win.txt"
    f.write_bytes(b"line1\r\nline2\r\nline3\r\n")
    result = await StrReplaceTool().execute(
        {
            "path": "win.txt",
            "old_string": "line1\nline2\n",
            "new_string": "lineA\n",
        },
        _ctx(tmp_path),
    )
    assert result.success is True
    assert result.metadata["replacements"] == 1
    assert f.read_bytes() == b"lineA\r\nline3\r\n"


async def test_replacement_inserts_new_text_verbatim(tmp_path: Path):
    f = tmp_path / "f.txt"
    f.write_text("key: old\n", encoding="utf-8")
    result = await StrReplaceTool().execute(
        {"path": "f.txt", "old_string": "old", "new_string": "new value 123"},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert f.read_text(encoding="utf-8") == "key: new value 123\n"
