"""Tests for SECTION inject (Wave3 A) and turn-ceiling light shell gaps (B3)."""

from pathlib import Path

import pytest

from agentcore.runtime.runs.website_section import (
    REASON_WEBSITE_SHELL,
    SectionMarkerError,
    collect_light_website_acceptance_gaps,
    inject_section_html,
    light_website_acceptance_gaps,
    normalize_section_id,
)
from agentcore.tools.builtin.file_ops import WriteSectionTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_normalize_section_id():
    assert normalize_section_id("s0") == "s0"
    assert normalize_section_id("S2") == "s2"
    assert normalize_section_id("3") == "s3"
    with pytest.raises(SectionMarkerError):
        normalize_section_id("")
    with pytest.raises(SectionMarkerError):
        normalize_section_id("hero")


def test_inject_section_ignores_indent_drift():
    html = (
        "<html><body>\n"
        "  <!-- SECTION:s0 START -->\n"
        "    <div class='ph'>  {{title}}  </div>\n"
        "  <!-- SECTION:s0 END -->\n"
        "  <!-- SECTION:s1 START -->\n"
        "  <!-- SECTION:s1 END -->\n"
        "</body></html>"
    )
    out = inject_section_html(html, "s0", "<section id='hero'><h1>Hi</h1></section>")
    assert "<!-- SECTION:s0 START -->" in out
    assert "<!-- SECTION:s0 END -->" in out
    assert "<section id='hero'><h1>Hi</h1></section>" in out
    assert "{{title}}" not in out
    # Sibling section untouched
    assert "<!-- SECTION:s1 START -->" in out
    assert "<!-- SECTION:s1 END -->" in out


def test_inject_section_missing_markers():
    with pytest.raises(SectionMarkerError, match="找不到"):
        inject_section_html("<html></html>", "s0", "<p>x</p>")


def test_light_gaps_missing_files_and_mustache():
    gaps = light_website_acceptance_gaps(
        present_paths={"site/styles.css"},
        html_texts={"site/index.html": "<h1>{{title}}</h1>"},
    )
    reasons = [g["reason"] for g in gaps]
    assert reasons.count(REASON_WEBSITE_SHELL) == 2
    descs = " ".join(g["description"] for g in gaps)
    assert "site/index.html" in descs and "site/main.js" in descs
    assert "{{" in descs or "模板槽" in descs


def test_light_gaps_clean_shell():
    gaps = light_website_acceptance_gaps(
        present_paths={
            "site/index.html",
            "site/styles.css",
            "site/main.js",
        },
        html_texts={"site/index.html": "<h1>Ready</h1>"},
    )
    assert gaps == []


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
    )


@pytest.mark.asyncio
async def test_write_section_from_file_tolerates_blank_interior(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        "<html>\n"
        "<!-- SECTION:s0 START -->\n"
        "\n\n    \n"
        "<!-- SECTION:s0 END -->\n"
        "</html>\n",
        encoding="utf-8",
    )
    sections = site / "sections"
    sections.mkdir()
    (sections / "s0.html").write_text(
        "<section class='hero'><h1>Filled</h1></section>\n",
        encoding="utf-8",
    )
    result = await WriteSectionTool().execute(
        {
            "path": "site/index.html",
            "section": "s0",
            "from_file": "site/sections/s0.html",
        },
        _ctx(tmp_path),
    )
    assert result.success is True
    body = (site / "index.html").read_text(encoding="utf-8")
    assert "Filled" in body
    assert "SECTION:s0 START" in body and "SECTION:s0 END" in body


@pytest.mark.asyncio
async def test_write_section_content_and_reject_both_sources(tmp_path: Path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text(
        "<!-- SECTION:s1 START --><!-- SECTION:s1 END -->",
        encoding="utf-8",
    )
    bad = await WriteSectionTool().execute(
        {
            "path": "site/index.html",
            "section": "s1",
            "content": "<p>a</p>",
            "from_file": "site/sections/s1.html",
        },
        _ctx(tmp_path),
    )
    assert bad.success is False
    assert "只能提供其一" in (bad.error or "")

    ok = await WriteSectionTool().execute(
        {"path": "site/index.html", "section": "s1", "content": "<p>ok</p>"},
        _ctx(tmp_path),
    )
    assert ok.success is True
    assert "<p>ok</p>" in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_collect_light_gaps_from_workspace(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<div>{{slot}}</div>", encoding="utf-8")
    # styles/main missing → critical-file gap + mustache gap
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    gaps = await collect_light_website_acceptance_gaps(backend)
    assert any(g["reason"] == REASON_WEBSITE_SHELL for g in gaps)
    descs = " ".join(g["description"] for g in gaps)
    assert "styles.css" in descs or "main.js" in descs
    assert "模板槽" in descs or "{{" in descs


@pytest.mark.asyncio
async def test_attach_light_gaps_on_qa_skip(tmp_path: Path):
    from unittest.mock import MagicMock

    from agentcore.runtime.delegate.drive import (
        _attach_light_website_gaps,
        _materialise_turn_token_budget_skips,
    )
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import Deliverable, RunPhase, RunSpec, RunState

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>{{todo}}</p>", encoding="utf-8")

    plan = RunPlan()
    plan.add(
        RunSpec(
            run_id="qa",
            role="页面 QA",
            task="qa",
            agent_id="qa",
            ceiling_priority=True,
            deliverable=Deliverable(
                name="QA",
                form="files",
                artifacts=["site/QA.md"],
                web_quality_scan=True,
                visual_critic=True,
            ),
        )
    )
    results: dict[str, RunState] = {}
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._base_tool_context = MagicMock()
    tool._base_tool_context.backend = ServerWorkspace(
        root=tmp_path, sandbox=SubprocessSandbox()
    )
    _materialise_turn_token_budget_skips(tool, plan, results)
    assert results["qa"].phase is RunPhase.SKIPPED
    await _attach_light_website_gaps(tool, results)
    reasons = [g["reason"] for g in results["qa"].delivery_gaps]
    assert "qa_deferred_budget" in reasons
    assert REASON_WEBSITE_SHELL in reasons
