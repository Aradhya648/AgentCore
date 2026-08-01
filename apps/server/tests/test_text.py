"""Unit tests for the leaf text primitives in ``core.text``."""

from __future__ import annotations

from agentcore.core.text import DEFAULT_ELISION_MARKER, clip_preview, truncate_head_tail


def test_keeps_both_ends_with_marker_between():
    content = "HEAD起始" + ("x" * 5_000) + "TAIL尾注金额￥999"
    out = truncate_head_tail(content, 1_000)
    assert out.startswith("HEAD起始")  # head (framing) kept
    assert out.endswith("TAIL尾注金额￥999")  # tail kept — a head-only cut drops it
    assert "系统视图截断" in out  # transport marker — not delivery-omission wording
    assert "中间省略" not in out
    assert "已保留首尾" not in out
    assert len(out) <= 1_000  # never exceeds the allowance


def test_default_marker_is_not_delivery_omission_wording():
    from agentcore.core.text import DELIVERY_OMISSION_MARKER

    assert "中间省略" not in DEFAULT_ELISION_MARKER
    assert "已保留首尾" not in DEFAULT_ELISION_MARKER
    assert "系统视图截断" in DEFAULT_ELISION_MARKER
    assert "中间省略" in DELIVERY_OMISSION_MARKER  # documented twin only


def test_noop_when_within_limit():
    assert truncate_head_tail("short", 1_000) == "short"


def test_empty_when_limit_non_positive():
    assert truncate_head_tail("anything", 0) == ""
    assert truncate_head_tail("anything", -5) == ""


def test_custom_marker_is_used():
    out = truncate_head_tail("HEAD" + ("x" * 500) + "TAIL", 120, marker="\n…我的标记…\n")
    assert "我的标记" in out
    assert DEFAULT_ELISION_MARKER not in out
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")


def test_degenerate_tiny_budget_falls_back_to_head_plus_ellipsis():
    # Budget smaller than the marker → head-only cut + ellipsis (real budgets never hit).
    out = truncate_head_tail("a" * 100, 10)
    assert out.startswith("a")
    assert out.endswith("…")


# --- clip_preview: the canonical single-line log-preview shaper ---


def test_clip_preview_collapses_all_whitespace_to_single_spaces():
    # A multi-line prompt / task / feedback must fit ONE log field: newlines, tabs and
    # runs of spaces all collapse to single spaces, with the ends trimmed.
    assert clip_preview("  a\n\n  b\t\tc   ", 100) == "a b c"


def test_clip_preview_head_clips_with_single_ellipsis():
    out = clip_preview("x" * 300, 200)
    assert out == "x" * 200 + "…"
    assert len(out) == 201  # 200-char head + the one ellipsis char


def test_clip_preview_noop_when_within_limit():
    assert clip_preview("short 文本", 200) == "short 文本"


def test_clip_preview_empty_and_none_are_safe():
    assert clip_preview("", 200) == ""
    assert clip_preview("   \n  ", 200) == ""  # whitespace-only collapses to empty
