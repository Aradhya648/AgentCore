"""Unit tests for the finish_guard delivery-verification light layer (交付前核验·轻层).

Mirrors the check_contract / out_of_range_markers test posture: finish_guard is a
pure function over ``(content, citation_count)`` returning concrete rework items, and
format_guard_steer renders them into one injected ``[系统提示]``. Coverage spans the
two light-layer checks: fabricated citations and structural completeness (unclosed /
empty-bodied code fences).
"""

from agentcore.runtime.verify import finish_guard, format_guard_steer


def test_in_range_citations_pass():
    assert finish_guard("结论见 [1] 与 [2]。", citation_count=2) == []


def test_no_marker_content_passes():
    assert finish_guard("一段没有任何角标的正文。", citation_count=0) == []


def test_out_of_range_marker_flagged():
    reworks = finish_guard("依据 [3] 可知……", citation_count=2)
    assert len(reworks) == 1
    assert "[3]" in reworks[0]
    assert "编造引用" in reworks[0]


def test_no_citations_flags_any_marker():
    # 0 来源时正文出现 [n] = 编造（与客户端「越界角标降级为纯文本」同义）。
    reworks = finish_guard("据来源 [1] 表明……", citation_count=0)
    assert reworks
    assert "[1]" in reworks[0]


def test_multiple_stray_markers_listed_in_one_item():
    # 镜像真实事故：24 源却写了 [25][27] —— 一条修正项里点名所有越界角标。
    reworks = finish_guard("见 [25] 和 [27]。", citation_count=24)
    assert len(reworks) == 1
    assert "[25]" in reworks[0]
    assert "[27]" in reworks[0]


def test_code_fence_markers_ignored():
    # 复用 out_of_range_markers 的抠除：代码块里的数组下标不是引用角标。
    content = "正文 [1]。\n```python\nfoo = arr[9]\n```\n"
    assert finish_guard(content, citation_count=1) == []


def test_empty_content_passes():
    assert finish_guard("", citation_count=0) == []
    assert finish_guard("   ", citation_count=0) == []


def test_closed_nonempty_fence_passes():
    content = "见下例：\n```python\nprint('hi')\n```\n收工。"
    assert finish_guard(content, citation_count=0) == []


def test_unclosed_fence_flagged():
    reworks = finish_guard("步骤如下：\n```python\nprint(1)", citation_count=0)
    assert len(reworks) == 1
    assert "没有闭合" in reworks[0]


def test_empty_fence_with_language_flagged():
    reworks = finish_guard("示例：\n```python\n```\n", citation_count=0)
    assert len(reworks) == 1
    assert "python" in reworks[0]
    assert "空" in reworks[0]


def test_bare_empty_fence_not_flagged():
    # 无语言标注的空围栏可能是有意排版，保守起见不判（守住近零误报）。
    assert finish_guard("```\n```\n", citation_count=0) == []


def test_indented_empty_fence_flagged():
    # 列表内缩进的围栏（lstrip 后仍是 ```）照样检出。
    reworks = finish_guard("- 代码：\n  ```json\n  ```\n", citation_count=0)
    assert len(reworks) == 1
    assert "json" in reworks[0]


def test_citation_and_structure_combine():
    # 造引用 + 空代码块 = 两条独立修正项。
    content = "见 [5]。\n```python\n```\n"
    reworks = finish_guard(content, citation_count=2)
    assert len(reworks) == 2
    assert any("编造引用" in r for r in reworks)
    assert any("空" in r for r in reworks)


def test_format_steer_renders_problems():
    steer = format_guard_steer(["问题甲", "问题乙"])
    assert steer.startswith("[系统提示]")
    assert "问题甲" in steer
    assert "问题乙" in steer
    assert "核验未通过" in steer


def test_format_steer_empty_when_clean():
    assert format_guard_steer([]) == ""


def test_format_steer_marks_automated_and_suppresses_acknowledgement():
    # 这条 steer 以 role=user 进窗口，模型易把它当用户纠错而回「谢谢指正」——那句寒暄会漏进
    # 可见交付（真实事故）。文案须自证是系统自动核验、非用户，并禁止致谢/复述/寒暄。
    steer = format_guard_steer(["问题甲"])
    assert "自动核验" in steer
    assert "非用户" in steer
    assert "道谢" in steer


def test_guard_to_steer_roundtrip():
    # finish_guard 命中 → format_guard_steer 出一条非空提示；干净 → 空串。
    assert format_guard_steer(finish_guard("坏引用 [9]", citation_count=1)).startswith("[系统提示]")
    assert format_guard_steer(finish_guard("好引用 [1]", citation_count=1)) == ""


def test_ledger_ref_gate_dual_track():
    # #rN 轨：合法放行；伪造回炉项；无标记不启用（Q5）。
    assert (
        finish_guard(
            "见 #r1。",
            citation_count=0,
            check_citations=False,
            citable_ids=frozenset({"#r1"}),
        )
        == []
    )
    bad = finish_guard(
        "见 #r9。",
        citation_count=0,
        check_citations=False,
        citable_ids=frozenset({"#r1"}),
    )
    assert bad and "#r9" in bad[0]
    assert (
        finish_guard(
            "无标记正文",
            citation_count=0,
            check_citations=False,
            citable_ids=frozenset(),
        )
        == []
    )
