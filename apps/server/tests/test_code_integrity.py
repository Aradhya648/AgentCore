"""Unit tests for brace-code integrity gate (D1 truncated class/file writes)."""

from pathlib import Path

from agentcore.tools.builtin.code_integrity import (
    code_structure_rejection,
    is_brace_code_path,
)
from agentcore.tools.builtin.file_ops import FileAppendTool, FileWriteTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="r",
        agent_id="a",
        backend=ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox()),
        user_id="u",
    )


def test_is_brace_code_path_suffixes():
    assert is_brace_code_path("src/canvas/renderer.ts")
    assert is_brace_code_path("App.tsx")
    assert is_brace_code_path("styles/main.css")
    assert not is_brace_code_path("README.md")
    assert not is_brace_code_path("main.py")


def test_code_structure_rejects_missing_class_brace():
    body = (
        "export class Renderer {\n"
        "  constructor() {\n"
        "    this.ready = true;\n"
        "  }\n"
    )  # missing closing brace for class
    err = code_structure_rejection("src/canvas/renderer.ts", body)
    assert err is not None
    assert "未闭合" in err
    assert "renderer.ts" in err


def test_code_structure_accepts_balanced_and_strings():
    body = (
        "export class Ok {\n"
        "  msg = \"{ not a brace\";\n"
        "  run() { return 1; }\n"
        "}\n"
    )
    assert code_structure_rejection("ok.ts", body) is None
    # comments with braces ignored
    commented = "export const x = 1; // { open\n/* { block } */\n"
    assert code_structure_rejection("x.js", commented) is None


async def test_file_write_rejects_truncated_ts(tmp_path: Path):
    truncated = "export class SelectTool {\n  constructor() {\n"
    result = await FileWriteTool().execute(
        {"path": "src/tools/select-tool.ts", "content": truncated},
        _ctx(tmp_path),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "结构不完整" in (result.error or "")
    assert not (tmp_path / "src/tools/select-tool.ts").exists()


async def test_file_write_allows_skeleton_unbalanced(tmp_path: Path):
    skeleton = (
        "<!-- SECTION:body -->\n"
        "export class WIP {\n"
        "  // fill later\n"
    )
    result = await FileWriteTool().execute(
        {"path": "src/wip.ts", "content": skeleton},
        _ctx(tmp_path),
    )
    assert result.success is True
    assert (tmp_path / "src/wip.ts").read_text(encoding="utf-8") == skeleton


async def test_file_write_rejects_omission_in_ts(tmp_path: Path):
    body = (
        "export function a() { return 1; }\n"
        "……（中间省略，已保留首尾）……\n"
        "export function z() { return 2; }\n"
    )
    result = await FileWriteTool().execute(
        {"path": "src/mod.ts", "content": body},
        _ctx(tmp_path),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "省略标记" in (result.error or "")


async def test_file_append_rejects_still_unbalanced(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "partial.ts").write_text(
        "export class A {\n  x = 1;\n",
        encoding="utf-8",
    )
    result = await FileAppendTool().execute(
        {"path": "src/partial.ts", "content": "  y = 2;\n"},
        _ctx(tmp_path),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "结构不完整" in (result.error or "")


async def test_file_append_accepts_closing_brace(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "partial.ts").write_text(
        "export class A {\n  x = 1;\n",
        encoding="utf-8",
    )
    result = await FileAppendTool().execute(
        {"path": "src/partial.ts", "content": "}\n"},
        _ctx(tmp_path),
    )
    assert result.success is True
    text = (tmp_path / "src" / "partial.ts").read_text(encoding="utf-8")
    assert text.endswith("}\n")
