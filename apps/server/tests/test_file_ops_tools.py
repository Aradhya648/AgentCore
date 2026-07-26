"""Tests for the file_write, file_delete and file_move tools (mutating file ops).

Hermetic: every test runs against a throwaway ``ServerWorkspace`` rooted at
``tmp_path`` and inspects the real on-disk result, mirroring the str_replace tool
tests. These tools are thin shells, so the focus is argument handling and the
typed-failure → user-message mapping (the heavy I/O lives in the backend).
"""

from pathlib import Path

from agentcore.tools.builtin.file_ops import (
    FileAppendTool,
    FileBatchTool,
    FileCopyTool,
    FileDeleteTool,
    FileListTool,
    FileMoveTool,
    FileReadTool,
    FileWriteTool,
    MkdirTool,
    expand_brace_globs,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(workspace: Path, *, agent_id: str = "a") -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id=agent_id,
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
    )


# --- file_write ---


async def test_write_creates_file(tmp_path: Path):
    result = await FileWriteTool().execute(
        {"path": "notes/report.md", "content": "# Hi"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "notes" / "report.md").read_text(encoding="utf-8") == "# Hi"


async def test_write_rejects_substantial_overwrite(tmp_path: Path):
    body = "成篇正文。" * 80  # well over substantial threshold
    target = tmp_path / "site" / "index.html"
    target.parent.mkdir(parents=True)
    target.write_text(body, encoding="utf-8")
    result = await FileWriteTool().execute(
        {"path": "site/index.html", "content": "<html>rewrite</html>"},
        _ctx(tmp_path),
    )
    assert result.success is False
    assert "拒绝整文件覆盖" in (result.error or "")
    assert "str_replace" in (result.error or "")
    assert result.contract_failure is True
    assert target.read_text(encoding="utf-8") == body


async def test_write_allows_tiny_overwrite(tmp_path: Path):
    (tmp_path / "stub.txt").write_text("tiny", encoding="utf-8")
    result = await FileWriteTool().execute(
        {"path": "stub.txt", "content": "still small"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "stub.txt").read_text(encoding="utf-8") == "still small"


async def test_write_rejects_non_empty_code_overwrite(tmp_path: Path):
    """短非空代码文件也不能骨架整写冒充修复（阶段3）。"""
    body = "export function TopBar() {\n  return <header>App</header>;\n}\n"
    target = tmp_path / "src" / "TopBar.tsx"
    target.parent.mkdir(parents=True)
    target.write_text(body, encoding="utf-8")
    skeleton = "export function TopBar() {\n  return null;\n}\n"
    result = await FileWriteTool().execute(
        {"path": "src/TopBar.tsx", "content": skeleton},
        _ctx(tmp_path),
    )
    assert result.success is False
    assert "拒绝整文件覆盖" in (result.error or "")
    assert "非空代码" in (result.error or "")
    assert "str_replace" in (result.error or "")
    assert result.contract_failure is True
    assert target.read_text(encoding="utf-8") == body


async def test_write_allows_empty_code_shell(tmp_path: Path):
    """真·空壳（空白）代码文件仍可用 file_write 写入。"""
    target = tmp_path / "src" / "NewWidget.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("   \n", encoding="utf-8")
    content = "export function NewWidget() {\n  return null;\n}\n"
    result = await FileWriteTool().execute(
        {"path": "src/NewWidget.tsx", "content": content},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert target.read_text(encoding="utf-8") == content


async def test_write_allows_new_code_file(tmp_path: Path):
    content = "export const x = 1;\n"
    result = await FileWriteTool().execute(
        {"path": "src/fresh.ts", "content": content},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert (tmp_path / "src" / "fresh.ts").read_text(encoding="utf-8") == content


async def test_write_rejects_empty_path(tmp_path: Path):
    # A worker that omits/empties ``path`` must get a crisp required-arg error — NOT
    # a backend write onto the workspace root dir (the real-world file_write failure:
    # path=None → root → "[Errno 13] Permission denied: <abs server path>").
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    result = await FileWriteTool().execute({"path": "", "content": "x" * 5000}, _ctx(tmp_path))
    assert result.success is False
    assert "path 不能为空" in result.error
    # the root must be untouched (no clobber, no stray file)
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "keep"


async def test_write_rejects_missing_path(tmp_path: Path):
    result = await FileWriteTool().execute({"content": "body"}, _ctx(tmp_path))
    assert result.success is False
    assert "path 不能为空" in result.error


async def test_write_rejects_path_outside_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    result = await FileWriteTool().execute({"path": "../escaped.md", "content": "leak"}, _ctx(ws))
    assert result.success is False
    assert "超出了工作区范围" in result.error
    assert not (tmp_path / "escaped.md").exists()


async def test_write_normalizes_absolute_workspace_path(tmp_path: Path):
    # A worker passing an absolute /workspace/... path now succeeds (normalized at the
    # path-resolution seam) instead of failing OutsideWorkspace and retrying.
    result = await FileWriteTool().execute(
        {"path": "/workspace/research/x.md", "content": "hi"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "research" / "x.md").read_text(encoding="utf-8") == "hi"


async def test_outside_workspace_error_is_actionable(tmp_path: Path):
    # The rejection tells the model exactly how to fix it (relative path + example),
    # not just that the path was out of range. Cloud workspace also nudges the bind card.
    ws = tmp_path / "ws"
    ws.mkdir()
    result = await FileWriteTool().execute({"path": "../escaped.md", "content": "x"}, _ctx(ws))
    assert result.success is False
    assert "超出了工作区范围" in result.error
    assert "相对路径" in result.error
    assert "AgentCore/文档/research/report.md" in result.error
    assert "bind_local_folder" in result.error
    assert "勿用纯文本" in result.error


# --- file_read (Wave3 B same-path ceiling) ---


async def test_file_read_allows_up_to_same_path_max(tmp_path: Path):
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "CONTRACT.md").write_text("# CONTRACT\nbody", encoding="utf-8")
    ctx = _ctx(tmp_path)
    tool = FileReadTool()
    for i in range(FILE_READ_SAME_PATH_MAX):
        result = await tool.execute({"path": "site/CONTRACT.md"}, ctx)
        assert result.success is True, i
        assert "CONTRACT" in (result.output or "")
    assert ctx.file_read_counts.get("site/CONTRACT.md") == FILE_READ_SAME_PATH_MAX


async def test_file_read_rejects_same_path_over_max(tmp_path: Path):
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "DESIGN.md").write_text("tokens", encoding="utf-8")
    ctx = _ctx(tmp_path)
    tool = FileReadTool()
    for _ in range(FILE_READ_SAME_PATH_MAX):
        assert (await tool.execute({"path": "site/DESIGN.md"}, ctx)).success is True
    blocked = await tool.execute({"path": "site/DESIGN.md"}, ctx)
    assert blocked.success is False
    assert blocked.contract_failure is True
    assert "已多次读取" in (blocked.error or "")
    assert "site/DESIGN.md" in (blocked.error or "")


async def test_file_read_same_path_limit_is_per_path(tmp_path: Path):
    (tmp_path / "a.md").write_text("A", encoding="utf-8")
    (tmp_path / "b.md").write_text("B", encoding="utf-8")
    ctx = _ctx(tmp_path)
    tool = FileReadTool()
    assert (await tool.execute({"path": "a.md"}, ctx)).success is True
    assert (await tool.execute({"path": "b.md"}, ctx)).success is True
    assert (await tool.execute({"path": "a.md"}, ctx)).success is True
    assert ctx.file_read_counts["a.md"] == 2
    assert ctx.file_read_counts["b.md"] == 1


async def test_file_read_reread_after_clear_allows_one(tmp_path: Path):
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    (tmp_path / "doc.md").write_text("# Doc\nbody", encoding="utf-8")
    ctx = _ctx(tmp_path)
    tool = FileReadTool()
    for _ in range(FILE_READ_SAME_PATH_MAX):
        assert (await tool.execute({"path": "doc.md"}, ctx)).success is True
    # Projection synced: zero verbatim + sticky grant → one more success.
    ctx.file_read_verbatim_paths = frozenset()
    ctx.file_read_reread_issued["doc.md"] = True
    ctx.file_read_reread_remaining["doc.md"] = 1
    ok = await tool.execute({"path": "doc.md"}, ctx)
    assert ok.success is True
    assert ctx.file_read_counts["doc.md"] == FILE_READ_SAME_PATH_MAX + 1
    assert ctx.file_read_reread_remaining["doc.md"] == 0
    assert "再读次数已用尽" in (ok.output or "")
    # Grant exhausted → new copy (must not claim body still in dialogue).
    blocked = await tool.execute({"path": "doc.md"}, ctx)
    assert blocked.success is False
    assert blocked.contract_failure is True
    assert "再读次数已用尽" in (blocked.error or "")
    assert "请使用对话中已有正文" not in (blocked.error or "")


async def test_file_read_reread_not_granted_while_verbatim_present(tmp_path: Path):
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    ctx = _ctx(tmp_path)
    tool = FileReadTool()
    for _ in range(FILE_READ_SAME_PATH_MAX):
        assert (await tool.execute({"path": "keep.md"}, ctx)).success is True
    ctx.file_read_verbatim_paths = frozenset({"keep.md"})
    ctx.file_read_reread_remaining["keep.md"] = 1  # even if remaining set, body wins
    blocked = await tool.execute({"path": "keep.md"}, ctx)
    assert blocked.success is False
    assert blocked.contract_failure is True
    assert "请使用对话中已有正文" in (blocked.error or "")


# --- file_append ---


async def test_append_creates_file_when_missing(tmp_path: Path):
    result = await FileAppendTool().execute(
        {"path": "draft.md", "content": "# Intro"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "# Intro"


async def test_append_adds_to_existing_file(tmp_path: Path):
    (tmp_path / "draft.md").write_text("# Intro", encoding="utf-8")
    result = await FileAppendTool().execute(
        {"path": "draft.md", "content": "\n\n## Section 2"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "# Intro\n\n## Section 2"


async def test_append_rejects_empty_path(tmp_path: Path):
    result = await FileAppendTool().execute({"path": "", "content": "x"}, _ctx(tmp_path))
    assert result.success is False
    assert "path 不能为空" in result.error


async def test_append_rejects_directory_target(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    result = await FileAppendTool().execute({"path": "pkg", "content": "x"}, _ctx(tmp_path))
    assert result.success is False
    assert "不是文件" in result.error


async def test_append_receipt_echoes_merged_tail(tmp_path: Path):
    # append 回执改为 artifact manifest（含 end_preview），免掉纯回读自检。
    (tmp_path / "draft.md").write_text("# Intro", encoding="utf-8")
    result = await FileAppendTool().execute(
        {"path": "draft.md", "content": "\n\n## Section 2"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "## Section 2" in result.output  # end_preview / title_tree
    assert "artifact manifest" in result.output
    assert "优先用 manifest 验真" in result.output


async def test_write_receipt_notes_persisted(tmp_path: Path):
    # file_write 回执 = artifact manifest；优先 manifest 验真（非身份硬闸）。
    result = await FileWriteTool().execute(
        {"path": "report.md", "content": "# Hi\n\n## A\n"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "artifact manifest" in result.output
    assert "content_sha256:" in result.output
    assert "title_tree:" in result.output
    assert "优先用 manifest 验真" in result.output
    assert "kind: skeleton" in result.output


async def test_write_prose_then_append_rejected(tmp_path: Path):
    """成篇 file_write 后同 path file_append 硬拒（Artifact-first）。"""
    prose = "# 报告\n\n" + ("这是实质正文段落。" * 50)  # well over substantial
    assert len(prose) >= 400
    ctx = _ctx(tmp_path)
    w = await FileWriteTool().execute({"path": "essay.md", "content": prose}, ctx)
    assert w.success is True
    assert "kind: prose" in w.output
    assert ctx.landed_artifact_kinds.get("essay.md") == "prose"
    blocked = await FileAppendTool().execute(
        {"path": "essay.md", "content": "\n\n## 续章\n更多。"}, ctx
    )
    assert blocked.success is False
    assert blocked.contract_failure is True
    assert "拒绝追加" in (blocked.error or "")
    assert "str_replace" in (blocked.error or "")


async def test_write_skeleton_then_append_allowed(tmp_path: Path):
    skeleton = "# 报告\n\n## 一\n\n## 二\n\n<!-- OUTLINE -->\n"
    ctx = _ctx(tmp_path)
    w = await FileWriteTool().execute({"path": "report.md", "content": skeleton}, ctx)
    assert w.success is True
    assert ctx.landed_artifact_kinds.get("report.md") == "skeleton"
    a = await FileAppendTool().execute(
        {"path": "report.md", "content": "\n\n## 一\n\n正文填空。\n"}, ctx
    )
    assert a.success is True
    assert "artifact manifest" in a.output


async def test_file_read_allows_author_self_product(tmp_path: Path):
    """作者写后 body file_read 允许（与读者同 path cap）；计入成功读次数。"""
    ctx = _ctx(tmp_path)
    w = await FileWriteTool().execute(
        {"path": "out.md", "content": "# Title\n\n## Sec\nbody line\n"}, ctx
    )
    assert w.success is True
    assert ctx.landed_artifact_authors.get("out.md") == "a"
    ok = await FileReadTool().execute({"path": "out.md"}, ctx)
    assert ok.success is True
    assert "body line" in (ok.output or "")
    assert ctx.file_read_counts.get("out.md", 0) == 1


async def test_file_read_author_and_reader_share_same_path_cap(tmp_path: Path):
    """同 execution 共享 landed 表与计数器：作者与读者均受 FILE_READ_SAME_PATH_MAX。"""
    from dataclasses import replace

    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    author_ctx = _ctx(tmp_path, agent_id="writer")
    w = await FileWriteTool().execute(
        {"path": "shared.md", "content": "# Shared\n\nbody for downstream\n"},
        author_ctx,
    )
    assert w.success is True
    assert author_ctx.landed_artifact_kinds.get("shared.md") is not None

    reader_ctx = replace(author_ctx, agent_id="ceo", run_id="ceo-run")
    assert reader_ctx.landed_artifact_kinds is author_ctx.landed_artifact_kinds
    assert reader_ctx.file_read_counts is author_ctx.file_read_counts

    allowed = await FileReadTool().execute({"path": "shared.md"}, reader_ctx)
    assert allowed.success is True
    assert "body for downstream" in allowed.output
    assert reader_ctx.file_read_counts.get("shared.md", 0) == 1

    # Author may also body-read (no identity gate); shared counter advances.
    author_ok = await FileReadTool().execute({"path": "shared.md"}, author_ctx)
    assert author_ok.success is True
    assert author_ctx.file_read_counts.get("shared.md", 0) == 2

    # Exhaust remaining slots then both hit the same hard cap.
    while int(author_ctx.file_read_counts.get("shared.md", 0)) < FILE_READ_SAME_PATH_MAX:
        assert (
            await FileReadTool().execute({"path": "shared.md"}, author_ctx)
        ).success is True
    blocked_author = await FileReadTool().execute({"path": "shared.md"}, author_ctx)
    blocked_reader = await FileReadTool().execute({"path": "shared.md"}, reader_ctx)
    assert blocked_author.success is False and blocked_author.contract_failure is True
    assert blocked_reader.success is False and blocked_reader.contract_failure is True
    assert "已多次读取" in (blocked_author.error or "")
    assert "已多次读取" in (blocked_reader.error or "")


# --- file_write overwrite integrity nudge ---


async def test_write_nudge_on_omission_marker(tmp_path: Path):
    # Keep under substantial-overwrite threshold so soft nudge still applies.
    old = "A" * 120 + "\n完整中段内容\n" + "B" * 120
    assert len(old) < 400
    (tmp_path / "draft.md").write_text(old, encoding="utf-8")
    truncated = (
        "A" * 40
        + "\n……（中间省略，已保留首尾）……\n"
        + "B" * 40
    )
    result = await FileWriteTool().execute(
        {"path": "draft.md", "content": truncated}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == truncated
    assert "产物疑似不完整" in result.output
    assert "省略标记" in result.output
    assert "绝不代派" in result.output
    assert "绝不拦截本次写入" in result.output


async def test_write_nudge_on_severe_shrink(tmp_path: Path):
    old = "字" * 300
    assert len(old) < 400
    (tmp_path / "essay.md").write_text(old, encoding="utf-8")
    short = "字" * 100  # ~33% of old — below 60% threshold
    result = await FileWriteTool().execute(
        {"path": "essay.md", "content": short}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "essay.md").read_text(encoding="utf-8") == short
    assert "产物疑似不完整" in result.output
    assert "字数骤降" in result.output
    assert "绝不代派" in result.output


async def test_write_no_nudge_on_new_file(tmp_path: Path):
    # New file — even with omission-looking text — must not false-positive.
    body = "开头\n……（中间省略，已保留首尾）……\n结尾"
    result = await FileWriteTool().execute(
        {"path": "new.md", "content": body}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "产物疑似不完整" not in result.output


async def test_write_no_nudge_on_modest_edit(tmp_path: Path):
    old = "字" * 300
    assert len(old) < 400
    (tmp_path / "essay.md").write_text(old, encoding="utf-8")
    # ~80% of old length, no omission markers — normal small revision.
    modest = "字" * 240
    result = await FileWriteTool().execute(
        {"path": "essay.md", "content": modest}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "产物疑似不完整" not in result.output


def test_has_omission_marker_covers_en_and_cn():
    from agentcore.tools.builtin.file_ops import has_omission_marker, integrity_nudge_text

    assert has_omission_marker("……（中间省略，已保留首尾）……")
    assert has_omission_marker("正文（略）续")
    assert has_omission_marker("see ... omitted details")
    assert has_omission_marker("Truncated for brevity here")
    assert not has_omission_marker("正常全文无省略")
    text = integrity_nudge_text(
        path="a.md", reasons=["正文含省略标记"], old_chars=100, new_chars=40
    )
    assert "产物疑似不完整" in text
    assert "绝不代派" in text


# --- file_write oversized soft length nudge ---


async def test_write_length_nudge_on_oversized_content(tmp_path: Path):
    from agentcore.tools.builtin.file_ops import (
        _WRITE_LENGTH_WARN_CHARS,
        _WRITE_LENGTH_WARN_TOKENS,
    )

    body = "x" * _WRITE_LENGTH_WARN_CHARS
    result = await FileWriteTool().execute(
        {"path": "big.html", "content": body}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "big.html").read_text(encoding="utf-8") == body
    assert "内容较长" in result.output
    assert "Artifact-first" in result.output
    assert "短骨架" in result.output
    assert "绝不拦截本次写入" in result.output
    assert str(_WRITE_LENGTH_WARN_TOKENS) in result.output
    assert str(_WRITE_LENGTH_WARN_CHARS) in result.output


async def test_write_no_length_nudge_below_threshold(tmp_path: Path):
    from agentcore.tools.builtin.file_ops import _WRITE_LENGTH_WARN_CHARS

    body = "x" * (_WRITE_LENGTH_WARN_CHARS - 1)
    result = await FileWriteTool().execute(
        {"path": "ok.md", "content": body}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "内容较长" not in result.output
    assert "Artifact-first" not in result.output


async def test_write_then_append_segmented_path(tmp_path: Path):
    """建站 HTML 短骨架 + SECTION 填空：append 仍放行（勿误伤）。"""
    skeleton = (
        "<!doctype html>\n<html>\n<head></head>\n<body>\n"
        "<!-- SECTION:s0 START -->\n<!-- SECTION:s0 END -->\n"
    )
    section = "  <section>hello</section>\n"
    closing = "</body>\n</html>\n"

    ctx = _ctx(tmp_path)
    w = await FileWriteTool().execute(
        {"path": "site/index.html", "content": skeleton}, ctx
    )
    assert w.success is True
    assert "内容较长" not in w.output
    assert ctx.landed_artifact_kinds.get("site/index.html") == "skeleton"

    a1 = await FileAppendTool().execute(
        {"path": "site/index.html", "content": section}, ctx
    )
    assert a1.success is True
    assert "已追加" in a1.output

    a2 = await FileAppendTool().execute(
        {"path": "site/index.html", "content": closing}, ctx
    )
    assert a2.success is True
    merged = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert merged == skeleton + section + closing


def test_write_schema_teaches_artifact_first():
    write_desc = FileWriteTool().schema.description
    assert "Artifact-first" in write_desc
    assert "短骨架" in write_desc or "骨架" in write_desc
    assert "中间省略" in write_desc
    assert "manifest" in write_desc
    content_desc = FileWriteTool().schema.parameters["properties"]["content"]["description"]
    assert "骨架" in content_desc or "一次写完" in content_desc

    append_desc = FileAppendTool().schema.description
    assert "骨架" in append_desc
    assert "file_write" in append_desc
    assert "成篇" in append_desc or "禁止" in append_desc


def test_length_nudge_helpers_pin_threshold():
    from agentcore.tools.builtin.file_ops import (
        _CHARS_PER_TOKEN_EST,
        _WRITE_LENGTH_WARN_CHARS,
        _WRITE_LENGTH_WARN_TOKENS,
        is_oversized_write,
        length_nudge_text,
        write_length_nudge,
    )

    assert _WRITE_LENGTH_WARN_CHARS == _WRITE_LENGTH_WARN_TOKENS * _CHARS_PER_TOKEN_EST
    assert not is_oversized_write("x" * (_WRITE_LENGTH_WARN_CHARS - 1))
    assert is_oversized_write("x" * _WRITE_LENGTH_WARN_CHARS)
    assert write_length_nudge("a.md", "short") is None
    text = length_nudge_text(path="a.md", chars=_WRITE_LENGTH_WARN_CHARS)
    assert "Artifact-first" in text
    assert "绝不拦截本次写入" in text


def test_classify_write_kind_helpers():
    from agentcore.tools.builtin.file_ops import (
        classify_write_kind,
        extract_title_tree,
        has_skeleton_markers,
    )

    assert has_skeleton_markers("<!-- SECTION:s0 START -->")
    assert has_skeleton_markers("<!-- OUTLINE -->")
    assert classify_write_kind("# A\n\n## B\n\n<!-- OUTLINE -->\n") == "skeleton"
    assert classify_write_kind("短") == "skeleton"
    prose = "# T\n\n" + ("正文内容。" * 80)
    assert classify_write_kind(prose) == "prose"
    assert extract_title_tree("# Hello\n\n## World\n") == ["# Hello", "## World"]


# --- file_delete ---


async def test_delete_file(tmp_path: Path):
    (tmp_path / "f.txt").write_text("bye", encoding="utf-8")
    result = await FileDeleteTool().execute({"path": "f.txt"}, _ctx(tmp_path))
    assert result.success is True
    assert "可逆删除" in result.output
    assert not (tmp_path / "f.txt").exists()
    # Soft-deleted into workspace trash with restore metadata.
    trash = tmp_path / ".agentcore" / "trash"
    assert trash.is_dir()
    entries = list(trash.iterdir())
    assert len(entries) == 1
    assert (entries[0] / "meta.json").is_file()
    assert (entries[0] / "content").read_text(encoding="utf-8") == "bye"


async def test_delete_directory_recursive(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "pkg" / "sub").mkdir()
    (tmp_path / "pkg" / "sub" / "b.txt").write_text("b", encoding="utf-8")
    result = await FileDeleteTool().execute({"path": "pkg"}, _ctx(tmp_path))
    assert result.success is True
    assert not (tmp_path / "pkg").exists()
    assert (tmp_path / ".agentcore" / "trash").is_dir()


async def test_delete_permanent_hard_removes(tmp_path: Path):
    (tmp_path / "f.txt").write_text("bye", encoding="utf-8")
    result = await FileDeleteTool().execute(
        {"path": "f.txt", "permanent": True}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "永久删除" in result.output
    assert not (tmp_path / "f.txt").exists()
    trash = tmp_path / ".agentcore" / "trash"
    assert not trash.exists() or not any(trash.iterdir())


async def test_delete_not_found(tmp_path: Path):
    result = await FileDeleteTool().execute({"path": "nope.txt"}, _ctx(tmp_path))
    assert result.success is False
    assert "路径不存在" in result.error


async def test_delete_rejects_path_outside_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")
    result = await FileDeleteTool().execute({"path": "../secret.txt"}, _ctx(ws))
    assert result.success is False
    assert "超出了工作区范围" in result.error
    # the out-of-tree file must be untouched
    assert (tmp_path / "secret.txt").read_text(encoding="utf-8") == "top secret"


async def test_delete_refuses_workspace_root(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    result = await FileDeleteTool().execute({"path": ""}, _ctx(tmp_path))
    assert result.success is False
    # Empty path is rejected up-front (成篇 delete gate pre-read); "." still hits
    # OutsideWorkspace at the backend for genuine root deletes.
    assert "path 不能为空" in result.error or "超出了工作区范围" in result.error
    # nothing in the root was removed
    assert (tmp_path / "keep.txt").exists()


async def test_delete_refuses_dot_workspace_root(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    result = await FileDeleteTool().execute({"path": "."}, _ctx(tmp_path))
    assert result.success is False
    assert "超出了工作区范围" in result.error or "工作区根" in (result.error or "")
    assert (tmp_path / "keep.txt").exists()


# --- file_move ---


async def test_move_renames_file(tmp_path: Path):
    (tmp_path / "old.txt").write_text("data", encoding="utf-8")
    result = await FileMoveTool().execute(
        {"source": "old.txt", "destination": "new.txt"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "已把 old.txt 移动到 new.txt" in result.output
    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "data"


async def test_move_creates_destination_parents(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    result = await FileMoveTool().execute(
        {"source": "f.txt", "destination": "deep/nested/f.txt"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "deep" / "nested" / "f.txt").read_text(encoding="utf-8") == "x"


async def test_move_directory(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("a", encoding="utf-8")
    result = await FileMoveTool().execute({"source": "src", "destination": "dst"}, _ctx(tmp_path))
    assert result.success is True
    assert (tmp_path / "dst" / "a.txt").read_text(encoding="utf-8") == "a"
    assert not (tmp_path / "src").exists()


async def test_move_refuses_to_overwrite(tmp_path: Path):
    (tmp_path / "a.txt").write_text("from", encoding="utf-8")
    (tmp_path / "b.txt").write_text("to", encoding="utf-8")
    result = await FileMoveTool().execute(
        {"source": "a.txt", "destination": "b.txt"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "已存在" in result.error
    # both files must be untouched
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "from"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "to"


async def test_move_source_not_found(tmp_path: Path):
    result = await FileMoveTool().execute(
        {"source": "ghost.txt", "destination": "x.txt"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "源路径不存在" in result.error


async def test_move_rejects_path_outside_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside", encoding="utf-8")
    result = await FileMoveTool().execute(
        {"source": "inside.txt", "destination": "../escaped.txt"}, _ctx(ws)
    )
    assert result.success is False
    assert "超出了工作区范围" in result.error
    assert (ws / "inside.txt").read_text(encoding="utf-8") == "inside"
    assert not (tmp_path / "escaped.txt").exists()


async def test_move_requires_both_args(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    result = await FileMoveTool().execute({"source": "f.txt"}, _ctx(tmp_path))
    assert result.success is False
    assert "必填" in result.error


async def test_move_rejects_identical_paths(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    result = await FileMoveTool().execute(
        {"source": "f.txt", "destination": "f.txt"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "相同" in result.error
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "x"


# --- file_copy / mkdir / file_batch ---


async def test_copy_file_and_tree(tmp_path: Path):
    (tmp_path / "a.txt").write_text("data", encoding="utf-8")
    result = await FileCopyTool().execute(
        {"source": "a.txt", "destination": "b/c.txt"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "data"
    assert (tmp_path / "b" / "c.txt").read_text(encoding="utf-8") == "data"

    (tmp_path / "tree" / "sub").mkdir(parents=True)
    (tmp_path / "tree" / "sub" / "x.bin").write_bytes(b"\x00\xff")
    result = await FileCopyTool().execute(
        {"source": "tree", "destination": "tree2"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert (tmp_path / "tree2" / "sub" / "x.bin").read_bytes() == b"\x00\xff"


async def test_copy_refuses_overwrite(tmp_path: Path):
    (tmp_path / "a.txt").write_text("from", encoding="utf-8")
    (tmp_path / "b.txt").write_text("to", encoding="utf-8")
    result = await FileCopyTool().execute(
        {"source": "a.txt", "destination": "b.txt"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "已存在" in result.error


async def test_mkdir_creates_and_refuses_existing(tmp_path: Path):
    result = await MkdirTool().execute({"path": "out/docs"}, _ctx(tmp_path))
    assert result.success is True
    assert (tmp_path / "out" / "docs").is_dir()
    result = await MkdirTool().execute({"path": "out/docs"}, _ctx(tmp_path))
    assert result.success is False
    assert "已存在" in result.error


async def test_file_batch_partial_failure_continues(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    result = await FileBatchTool().execute(
        {
            "operations": [
                {"op": "mkdir", "path": "out"},
                {"op": "copy", "source": "a.txt", "destination": "out/a.txt"},
                {"op": "move", "source": "missing.txt", "destination": "out/m.txt"},
                {"op": "delete", "path": "ghost.txt"},
                {"op": "mkdir", "path": "out"},  # already exists → skip
            ]
        },
        _ctx(tmp_path),
    )
    assert result.success is False  # one hard failure (move missing)
    assert "本次共 5 项" in result.output
    assert "成功" in result.output
    assert "跳过" in result.output
    assert "失败" in result.output
    assert (tmp_path / "out" / "a.txt").read_text(encoding="utf-8") == "a"
    assert result.metadata["ok"] >= 2
    assert result.metadata["fail"] >= 1


# --- file_list ---


def test_expand_brace_globs_basic():
    assert expand_brace_globs("*.{ts,tsx}") == ["*.ts", "*.tsx"]
    assert expand_brace_globs("**/*.{py,pyi}") == ["**/*.py", "**/*.pyi"]
    assert expand_brace_globs("*.py") == ["*.py"]
    assert expand_brace_globs("*") == ["*"]


async def test_file_list_pattern_miss_does_not_say_empty_dir(tmp_path: Path):
    """Trace f69e97…: CEO `*.py` on `.` returned「空目录」though server/ client/ existed."""
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "client").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    result = await FileListTool().execute(
        {"directory": ".", "pattern": "*.py"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "空目录" not in result.output
    assert "无匹配 pattern='*.py'" in result.output
    assert "目录非空" in result.output
    assert "recursive=true" in result.output
    # Top-level sample should surface real dirs/files
    assert "server" in result.output or "client" in result.output


async def test_file_list_truly_empty_dir_still_says_empty(tmp_path: Path):
    empty = tmp_path / "blank"
    empty.mkdir()
    result = await FileListTool().execute(
        {"directory": "blank", "pattern": "*.py"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert result.output == "（空目录）"


async def test_file_list_brace_glob_matches_either_extension(tmp_path: Path):
    """pathlib does not expand `{a,b}` — without help, `*.{ts,tsx}` falsely empties."""
    src = tmp_path / "client" / "src"
    src.mkdir(parents=True)
    (src / "App.tsx").write_text("export {}", encoding="utf-8")
    (src / "api.ts").write_text("export {}", encoding="utf-8")
    (src / "readme.md").write_text("x", encoding="utf-8")

    result = await FileListTool().execute(
        {"directory": "client/src", "pattern": "*.{ts,tsx}"}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "空目录" not in result.output
    assert "App.tsx" in result.output
    assert "api.ts" in result.output
    assert "readme.md" not in result.output


async def test_file_list_recursive_pattern_miss_hint(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x", encoding="utf-8")
    result = await FileListTool().execute(
        {"directory": "pkg", "pattern": "*.rs", "recursive": True}, _ctx(tmp_path)
    )
    assert result.success is True
    assert "空目录" not in result.output
    assert "无匹配 pattern='*.rs'" in result.output
    assert "a.py" in result.output or "目录非空" in result.output
