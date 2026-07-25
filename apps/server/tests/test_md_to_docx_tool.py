"""md_to_docx tool — thin shell over docs_export.export_markdown_path."""

from __future__ import annotations

from pathlib import Path

from agentcore.tools.builtin.md_to_docx import MdToDocxTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
    )


async def test_md_to_docx_tool_writes_sibling_and_warns_missing_image(tmp_path: Path):
    (tmp_path / "note.md").write_text("# Hi\n\n![x](./gone.png)\n", encoding="utf-8")
    result = await MdToDocxTool().execute({"path": "note.md"}, _ctx(tmp_path))
    assert result.success is True
    assert (tmp_path / "note.docx").is_file()
    assert "note.docx" in result.output
    assert "缺图" in result.output
    assert result.metadata is not None
    assert result.metadata["path"] == "note.docx"


async def test_md_to_docx_tool_rejects_non_md(tmp_path: Path):
    result = await MdToDocxTool().execute({"path": "a.txt"}, _ctx(tmp_path))
    assert result.success is False
    assert result.error and "Markdown" in result.error
