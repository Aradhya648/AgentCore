"""辩手发言 → 结构化论点：title 完整入库，不在数据层截断。"""

from __future__ import annotations

from agentcore.runtime.debate.speech_parse import (
    argument_title,
    parse_speech_arguments,
    summarize_text,
)


def test_summarize_text_still_truncates_for_previews() -> None:
    long = "这是一段很长的论述内容用于测试截断逻辑是否正常工作"
    out = summarize_text(long, 12)
    assert len(out) <= 13
    assert out.endswith("…")


def test_argument_title_colon_label_keeps_full_clause() -> None:
    title = argument_title(
        "论点一：四叶花卉是公共元素，但LV的Monogram是独创作品。"
        "后面是补充论述。"
    )
    assert title == "论点一：四叶花卉是公共元素，但LV的Monogram是独创作品"
    assert not title.endswith("…")
    assert len(title) > 30


def test_parse_markdown_headers_keep_full_long_titles() -> None:
    t1 = "论点一：四叶花卉是公共元素，但LV的Monogram是独创作品"
    t2 = "论点二：LV四叶花图案经长期使用已获得“第二含义”"
    speech = (
        f"### {t1}\n"
        "正文说明公共元素与独创作品的界限。\n\n"
        f"### {t2}\n"
        "正文说明第二含义的认定路径。"
    )
    args = parse_speech_arguments(speech)
    assert len(args) == 2
    assert args[0].title == t1
    assert args[1].title == t2
    assert not args[0].title.endswith("…")
    assert not args[1].title.endswith("…")
    assert len(args[0].title) > 30
    assert "###" not in args[0].body
    assert args[0].body.startswith("正文说明")


def test_parse_skeleton_short_titles_unchanged() -> None:
    speech = (
        "### 成本可控可回收\n"
        "首年可降本约 18%。\n\n"
        "### 风险有明确兜底\n"
        "迁移期设熔断。"
    )
    args = parse_speech_arguments(speech)
    assert [a.title for a in args] == ["成本可控可回收", "风险有明确兜底"]
