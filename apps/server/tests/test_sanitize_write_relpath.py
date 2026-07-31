"""Unit tests for ``sanitize_write_relpath`` (write-path safety + dossier flatten)."""

from __future__ import annotations

from agentcore.workspace._paths import sanitize_write_relpath
from agentcore.workspace.stage_dirs import (
    DEBATE_PREFIX,
    PROJECT_DOCS_PREFIX,
    RESEARCH_PREFIX,
    REVIEWS_PREFIX,
)


def test_safe_relative_path_unchanged():
    assert sanitize_write_relpath("site/index.html") == "site/index.html"
    assert sanitize_write_relpath("src/a.py") == "src/a.py"


def test_dangerous_chars_in_segment():
    assert sanitize_write_relpath('site/foo:bar?.html') == "site/foo_bar_.html"
    assert sanitize_write_relpath("docs/a*b.md") == "docs/a_b.md"


def test_dossier_flattens_nested_to_filename():
    assert (
        sanitize_write_relpath(f"{RESEARCH_PREFIX}法庭迷局/UX系统设计.md")
        == f"{RESEARCH_PREFIX}法庭迷局_UX系统设计.md"
    )
    assert (
        sanitize_write_relpath(f"{REVIEWS_PREFIX}a/b/c.md")
        == f"{REVIEWS_PREFIX}a_b_c.md"
    )
    assert (
        sanitize_write_relpath(f"{DEBATE_PREFIX}子题\\笔记.md")
        == f"{DEBATE_PREFIX}子题_笔记.md"
    )
    assert (
        sanitize_write_relpath(f"{PROJECT_DOCS_PREFIX}深/层/案.md")
        == f"{PROJECT_DOCS_PREFIX}深_层_案.md"
    )


def test_dossier_unsafe_chars_in_flat_name():
    assert (
        sanitize_write_relpath(f'{RESEARCH_PREFIX}报告:终稿?.md')
        == f"{RESEARCH_PREFIX}报告_终稿_.md"
    )


def test_absolute_workspace_prefix_stripped_before_sanitize():
    assert sanitize_write_relpath("/workspace/research/x.md") == "research/x.md"
    assert (
        sanitize_write_relpath(f"/workspace/{RESEARCH_PREFIX}a/b.md")
        == f"{RESEARCH_PREFIX}a_b.md"
    )


def test_other_absolute_keeps_leading_slash():
    assert sanitize_write_relpath("/etc/passwd") == "/etc/passwd"


def test_empty_and_dot_passthrough():
    assert sanitize_write_relpath("") == ""
    assert sanitize_write_relpath(".") == "."


def test_traversal_segments_preserved_for_containment():
    assert sanitize_write_relpath("../etc/passwd") == "../etc/passwd"
    assert sanitize_write_relpath("a/../b") == "a/../b"
