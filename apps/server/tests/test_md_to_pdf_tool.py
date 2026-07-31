"""md_to_pdf tool — thin shell over docs_export.export_markdown_to_pdf_path."""

from __future__ import annotations

from pathlib import Path

from agentcore.tools.builtin.md_to_pdf import MdToPdfTool
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


async def test_md_to_pdf_tool_writes_sibling(tmp_path: Path):
    (tmp_path / "note.md").write_text("# Hi\n\n你好世界\n", encoding="utf-8")
    result = await MdToPdfTool().execute({"path": "note.md"}, _ctx(tmp_path))
    assert result.success is True
    assert (tmp_path / "note.pdf").is_file()
    assert (tmp_path / "note.pdf").read_bytes()[:4] == b"%PDF"
    assert "note.pdf" in result.output
    assert "code_execute" in MdToPdfTool().schema.description
    assert "不要用 code_execute" in MdToPdfTool().schema.description
    assert result.metadata is not None
    assert result.metadata["path"] == "note.pdf"


async def test_md_to_pdf_tool_rejects_non_md(tmp_path: Path):
    result = await MdToPdfTool().execute({"path": "a.txt"}, _ctx(tmp_path))
    assert result.success is False
    assert result.error and "Markdown" in result.error


async def test_md_to_pdf_tool_warns_on_image(tmp_path: Path):
    (tmp_path / "note.md").write_text("# Hi\n\n![x](./gone.png)\n", encoding="utf-8")
    result = await MdToPdfTool().execute({"path": "note.md"}, _ctx(tmp_path))
    assert result.success is True
    assert "不嵌入图片" in result.output
