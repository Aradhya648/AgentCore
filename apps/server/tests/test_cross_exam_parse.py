"""质询作答解析单测（markdown 标题主路径 + 段落配对 + 悬垂检测）。"""

from agentcore.runtime.debate.cross_exam_parse import (
    _UNSEGMENTED_POINTER,
    build_cross_exam_exchanges,
    looks_incomplete_cross_exam_answer,
    merge_cx_continuation,
    parse_cross_exam_response,
)


def test_parse_cross_exam_response_heading_sections():
    qs = [
        "收益量化口径是否计入了尾部风险？请是/否直接回答。",
        "若熔断触发、灰度止损，已投入成本由谁承担？",
    ]
    ans = (
        "### 质询一\n"
        "否，量化口径未含尾部风险【待核实·推断】。\n\n"
        "### 质询二\n"
        "成本由灰度预算池兜底、触发熔断即回滚【已核实·灰度预案v2】"
    )
    got = parse_cross_exam_response(qs, ans)
    assert len(got) == 2
    assert got[0].question == qs[0]
    assert "尾部" in got[0].answer
    assert got[1].question == qs[1]
    assert "灰度" in got[1].answer


def test_parse_discards_preamble_before_first_heading():
    qs = ["你这条有出处吗？"]
    raw = "好的，我已掌握材料，现在作答：\n### 质询一\n暂无统一出处【待核实·推断】"
    got = parse_cross_exam_response(qs, raw)
    assert len(got) == 1
    assert "出处" in got[0].answer
    assert "好的" not in got[0].answer


def test_parse_pads_missing_section_with_empty_answer():
    qs = ["Q1", "Q2"]
    ans = "### 质询一\n只答了第一条"
    got = parse_cross_exam_response(qs, ans)
    assert got[0].answer == "只答了第一条"
    assert got[1].answer == ""


def test_parse_paragraph_fallback_pairs_when_no_headings():
    """无标题但有空行段落 → 按段落顺序与题目配对（避免全文错挂第一题）。"""
    qs = ["收益是否计入尾部风险？", "熔断成本由谁承担？"]
    ans = (
        "否，口径未含尾部【待核实·推断】。\n\n"
        "成本由灰度预算池兜底【已核实·预案】。"
    )
    got = parse_cross_exam_response(qs, ans, side_key="pro")
    assert len(got) == 2
    assert "尾部" in got[0].answer
    assert "灰度" in got[1].answer
    assert got[1].answer != _UNSEGMENTED_POINTER


def test_parse_unsegmented_blob_points_remaining_to_first():
    """切段失败的单团块：首条挂全文，其余挂指针（不再空答伪装未作答）。"""
    qs = ["收益是否计入尾部风险？", "熔断成本由谁承担？"]
    ans = "作答：否，口径未含尾部【待核实·推断】；熔断成本归属未定。"
    got = parse_cross_exam_response(qs, ans, side_key="con")
    assert len(got) == 2
    assert "尾部" in got[0].answer
    assert got[1].answer == _UNSEGMENTED_POINTER


def test_parse_does_not_treat_json_as_structured_path():
    """JSON 路径已退役：无标题的 JSON 碎片走降级配对，不按数组项映射。"""
    qs = ["收益是否计入尾部风险？", "熔断成本由谁承担？"]
    raw = '[{"question_index": 1, "answer": "答一"}, {"question_index": 2, "answer": "答二"}]'
    got = parse_cross_exam_response(qs, raw, side_key="pro")
    assert len(got) == 2
    assert "question_index" in got[0].answer
    assert got[1].answer == _UNSEGMENTED_POINTER


def test_build_cross_exam_exchanges_single_question():
    qs = ["收益是否计入尾部风险？"]
    ans = "作答：否，口径未含尾部【待核实·推断】。"
    got = build_cross_exam_exchanges(qs, ans)
    assert len(got) == 1
    assert got[0].question == qs[0]
    assert "尾部" in got[0].answer


def test_build_cross_exam_exchanges_empty_answer():
    got = build_cross_exam_exchanges(["Q1", "Q2"], "")
    assert len(got) == 2
    assert all(ex.answer == "" for ex in got)


def test_section_split_ignores_decimal_like_line_starts():
    """行首「3.5 倍…」不得被数字分段误切为第 3 段；真「1. / 2.」标题仍切。"""
    qs = ["Q1", "Q2"]
    ans = (
        "1. 第一答：口径未含尾部【待核实·推断】。\n"
        "2. 第二答：成本由灰度预算池兜底；其中 3.5 倍杠杆不改变结论【已核实·预案】。"
    )
    got = build_cross_exam_exchanges(qs, ans)
    assert len(got) == 2
    assert "尾部" in got[0].answer
    assert "灰度" in got[1].answer
    assert "3.5" in got[1].answer


def test_section_split_does_not_treat_lone_decimal_as_section_marker():
    """全文以小数开头且无第二段标题时，不误切（回落单团块降级）。"""
    qs = ["Q1", "Q2"]
    ans = "3.5 倍杠杆下尾部风险被低估【待核实·推断】；另一点是熔断成本归属未定。"
    got = build_cross_exam_exchanges(qs, ans)
    assert len(got) == 2
    assert "3.5" in got[0].answer
    assert got[1].answer == _UNSEGMENTED_POINTER


def test_looks_incomplete_detects_dangling_colon():
    assert looks_incomplete_cross_exam_answer("但这一缺失不构成循环论证，理由是：")
    assert looks_incomplete_cross_exam_answer("### 质询一\n部分成立。但间接证据链完整：")
    assert not looks_incomplete_cross_exam_answer("否，口径未含尾部【待核实·推断】。")
    assert not looks_incomplete_cross_exam_answer("")


def test_looks_incomplete_detects_unclosed_list_tail():
    assert looks_incomplete_cross_exam_answer("依据如下：\n-")
    assert looks_incomplete_cross_exam_answer("分三点说明\n1.")
    assert not looks_incomplete_cross_exam_answer("依据如下：\n- 第一点已写完。")


def test_merge_cx_continuation_appends_tail_after_colon():
    prior = "### 质询一\n部分成立。理由是："
    cont = "间接证据链已闭合【已核实·判决书】。"
    assert merge_cx_continuation(prior, cont) == prior + cont


def test_merge_cx_continuation_prefers_full_rewrite_with_headings():
    prior = "### 质询一\n理由是："
    cont = "### 质询一\n否，已完整论证【待核实·推断】。\n\n### 质询二\n成本由预算池兜底。"
    assert merge_cx_continuation(prior, cont) == cont
