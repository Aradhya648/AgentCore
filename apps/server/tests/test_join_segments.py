"""Tests for multi-segment deliverable join + continuity steer."""

from agentcore.runtime.engine.segments import (
    deliverable_continuity_instruction,
    join_segments,
)


def test_join_segments_blank_line_between_paragraphs():
    assert join_segments("第一段。", "第二段。") == "第一段。\n\n第二段。"


def test_join_segments_empty_sides():
    assert join_segments("", "only") == "only"
    assert join_segments("only", "") == "only"
    assert join_segments("  ", "next") == "next"


def test_join_segments_strips_edge_whitespace():
    assert join_segments("前段。  \n", "\n  后段。") == "前段。\n\n后段。"


def test_join_segments_trims_restated_last_paragraph():
    prior = "背景说明如下，请先看完。\n\n方案如下：\n1. 先做 A"
    cont = "方案如下：\n1. 先做 A\n2. 再做 B"
    assert join_segments(prior, cont) == "背景说明如下，请先看完。\n\n方案如下：\n1. 先做 A\n2. 再做 B"


def test_join_segments_trims_suffix_prefix_overlap():
    prior = "最终结论是采用方案甲作为主线，并按下列步骤稳步推进落实。"
    cont = "并按下列步骤稳步推进落实。\n\n第一步：准备环境。"
    assert (
        join_segments(prior, cont)
        == "最终结论是采用方案甲作为主线，并按下列步骤稳步推进落实。\n\n第一步：准备环境。"
    )


def test_join_segments_short_overlap_kept():
    # Accidental short matches (below threshold) must not eat real content.
    assert join_segments("好的。", "好的，继续。") == "好的。\n\n好的，继续。"


def test_deliverable_continuity_instruction_includes_preview_and_steer():
    text = deliverable_continuity_instruction(prior_deliverable="已交付的前半段。")
    assert text.startswith("[系统提示]")
    assert "已交付的前半段。" in text
    assert "自然衔接" in text
    assert "不要复述" in text


def test_deliverable_continuity_instruction_truncates_long_preview():
    long = "字" * 800
    text = deliverable_continuity_instruction(prior_deliverable=long)
    assert "…" in text
    assert len(text) < len(long) + 200
