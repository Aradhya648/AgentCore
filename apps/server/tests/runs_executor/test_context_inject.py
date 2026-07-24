"""Wave3 B: forced context inject for partition workers (skeleton/contract summaries)."""

from pathlib import Path

import pytest

from agentcore.runtime.runs.executor_context import (
    _build_messages,
    _context_inject_blocks,
    load_context_inject_files,
)
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunSpec
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_context_inject_blocks_render_heading_and_paths():
    blocks = _context_inject_blocks(
        {"site/CONTRACT.md": "# CONTRACT\nid: hero", "site/DESIGN.md": "tokens"}
    )
    assert len(blocks) == 1
    assert "强制注入" in blocks[0].heading
    assert "site/CONTRACT.md" in blocks[0].body
    assert "id: hero" in blocks[0].body
    assert blocks[0].fidelity == "inject"
    assert "site/CONTRACT.md" in blocks[0].files


def test_context_inject_blocks_skip_empty():
    assert _context_inject_blocks(None) == []
    assert _context_inject_blocks({}) == []
    assert _context_inject_blocks({"a.md": "  "}) == []


@pytest.mark.asyncio
async def test_load_context_inject_files_truncates(tmp_path: Path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "CONTRACT.md").write_text("X" * 5000, encoding="utf-8")
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    loaded = await load_context_inject_files(
        backend, ["site/CONTRACT.md"], per_file_chars=200
    )
    assert "site/CONTRACT.md" in loaded
    assert len(loaded["site/CONTRACT.md"]) <= 220  # trim + marker headroom


def test_build_messages_includes_inject_block():
    plan = RunPlan()
    plan.add(
        RunSpec(
            run_id="s0",
            role="分区",
            task="写片段",
            agent_id="s0",
            context_inject_files=["site/CONTRACT.md"],
        )
    )
    msgs = _build_messages(
        plan,
        plan.by_id("s0"),
        {},
        "SYS",
        "建站",
        context_inject={"site/CONTRACT.md": "契约摘要行"},
    )
    user = msgs[1].content or ""
    assert "强制注入" in user
    assert "契约摘要行" in user
