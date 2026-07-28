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


def test_blocked_empty_delivery_rejects_false_completion_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="blocked", delivered_files=(), execution_id="e1"
    )
    reworks = finish_guard(
        "文件已生成，确认结果：`测试演示.pptx` 已存在于工作区根目录。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert len(reworks) == 1
    assert "交付验收" in reworks[0]
    assert "不得宣称" in reworks[0]


def test_blocked_empty_delivery_allows_honest_acknowledgment():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="blocked", delivered_files=(), execution_id="e1"
    )
    assert (
        finish_guard(
            "交付未过关：工作区仍无产物。你可以绑定本地目录后让我继续生成。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )


def test_delivery_claim_check_skipped_for_workers():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="blocked", delivered_files=(), execution_id="e1"
    )
    # Workers use check_citations=False — must not inherit CEO delivery claim gate.
    assert (
        finish_guard(
            "文件已生成并已落盘。",
            citation_count=0,
            check_citations=False,
            delivery_verdict=verdict,
        )
        == []
    )


def test_delivered_verdict_allows_completion_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="delivered",
        delivered_files=("测试演示.pptx",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "文件已生成：`测试演示.pptx` 已存在于工作区。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )


def test_partial_verdict_rejects_all_success_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    reworks = finish_guard(
        "团队已全部完成，所有任务都已就绪，请直接使用。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert len(reworks) == 1
    assert "部分未满足" in reworks[0]
    assert "全部完成" in reworks[0]


def test_partial_verdict_rejects_fully_usable_claim():
    """可用性诚实性：blocked/partial +「已完整可用」→ finish_guard 回炉。"""
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("site/index.html",),
        execution_id="e1",
    )
    reworks = finish_guard(
        "质检面板已完整可用，可以开始用了。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert len(reworks) == 1
    assert "已完整可用" in reworks[0] or "完整可用" in reworks[0]


def test_blocked_verdict_rejects_fully_usable_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="blocked",
        delivered_files=(),
        execution_id="e1",
    )
    reworks = finish_guard(
        "现在已经可以使用了。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert any("可用" in r for r in reworks)


def test_partial_verdict_allows_negated_fully_usable_phrase():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("site/index.html",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "尚未完整可用：交互层仍有缺口。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )


def test_partial_verdict_allows_honest_gap_summary():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "已落盘 `src/a.ts`；编译验收未过，尚有缺口，建议下回补跑验证。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )


def test_partial_verdict_allows_negated_all_success_phrase():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "尚未全部完成：工具层仍缺类型声明。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )


def test_blocked_with_files_rejects_all_success_not_file_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    # blocked + some files is unusual but state can be blocked when gaps dominate;
    # all-success still forbidden; bare「已落盘」alone is OK when files exist.
    verdict = DeliveryVerdict(
        state="blocked",
        delivered_files=("notes.md",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "笔记已落盘，但主产物未交付。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )
    reworks = finish_guard(
        "全部交付完成，可以收工。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert len(reworks) == 1
    assert "未满足" in reworks[0]


def test_notes_verdict_allows_all_success_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    # Soft warnings only → notes; do not treat as blocking gaps.
    verdict = DeliveryVerdict(
        state="notes",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "全部完成，产物见工作区。",
            citation_count=0,
            delivery_verdict=verdict,
            overview_max_chars=1000,
        )
        == []
    )


def test_delivery_verdict_rejects_oversized_overview():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="delivered",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    body = "结论：已落盘。" + ("细节复述。" * 200)  # >> 1000
    reworks = finish_guard(
        body,
        citation_count=0,
        delivery_verdict=verdict,
        overview_max_chars=1000,
    )
    assert len(reworks) == 1
    assert "简短概览" in reworks[0]
    assert "1000" in reworks[0]


def test_delivery_verdict_allows_short_overview():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="delivered",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "已落盘 `src/a.ts`，详见产物卡。编译已过。",
            citation_count=0,
            delivery_verdict=verdict,
            overview_max_chars=1000,
        )
        == []
    )


def test_no_delivery_verdict_skips_overview_length_gate():
    # Prose / research turns with no delivery card — long answers OK.
    long = "调研结论。" * 400
    assert (
        finish_guard(
            long,
            citation_count=0,
            delivery_verdict=None,
            overview_max_chars=1000,
        )
        == []
    )


def test_overview_length_gate_disabled_when_max_nonpositive():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="delivered",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    body = "x" * 2000
    assert (
        finish_guard(
            body,
            citation_count=0,
            delivery_verdict=verdict,
            overview_max_chars=0,
        )
        == []
    )


def test_overview_length_skipped_for_workers():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="delivered",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "x" * 2000,
            citation_count=0,
            check_citations=False,
            delivery_verdict=verdict,
            overview_max_chars=1000,
        )
        == []
    )


def test_partial_md_only_rejects_pptx_ready_claim():
    """选了 pptx 却只落 md/脚本：假「PPT 已可打开」必须被 finish_guard 拦回。"""
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("build_pptx.py", "讲稿.md"),
        execution_id="e1",
    )
    reworks = finish_guard(
        "课件 PPT 已落盘，可直接打开使用。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert len(reworks) == 1
    assert ".pptx" in reworks[0]
    assert "不得宣称" in reworks[0]


def test_partial_md_only_allows_honest_pptx_gap():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("build_pptx.py", "讲稿.md"),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "讲稿与生成脚本已落盘；pptx 尚未生成，请绑定本地目录后运行脚本。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )


def test_pptx_landed_allows_pptx_ready_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="delivered",
        delivered_files=("course.pptx", "讲稿.md"),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "课件 PPT 已落盘，可直接打开使用。",
            citation_count=0,
            delivery_verdict=verdict,
            overview_max_chars=1000,
        )
        == []
    )


def test_pptx_claim_skipped_for_workers():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("讲稿.md",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "PPT 已落盘，可直接打开。",
            citation_count=0,
            check_citations=False,
            delivery_verdict=verdict,
        )
        == []
    )


def test_negated_pptx_claim_allowed_when_md_only():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("讲稿.md",),
        execution_id="e1",
    )
    assert (
        finish_guard(
            "尚未交付 PPT：目前只有讲稿大纲。",
            citation_count=0,
            delivery_verdict=verdict,
        )
        == []
    )
