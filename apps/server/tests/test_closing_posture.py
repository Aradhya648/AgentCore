"""收口诚实性（closing_posture）：档位真源 + 薄 A 闭集 + resume 拼接。"""

from agentcore.runtime.closing_posture import (
    claims_full_delivery,
    claims_needs_confirm,
    claims_posture_a,
    claims_posture_c,
    closing_honesty_rework,
    is_formal_complete_tier,
    mutual_exclusion_rework,
    reconcile_resume_closing,
    resume_continuity_steer,
    tier_forbids_posture_a,
)
from agentcore.runtime.verify import finish_guard


def test_tier_truth_source():
    assert is_formal_complete_tier("delivered")
    assert not is_formal_complete_tier("partial")
    assert not is_formal_complete_tier("notes")
    assert not is_formal_complete_tier("blocked")
    assert tier_forbids_posture_a("partial")
    assert tier_forbids_posture_a("notes")
    assert tier_forbids_posture_a("blocked")
    assert not tier_forbids_posture_a("delivered")


def test_cef27dfa_auc_same_message_flagged():
    """cef27dfa：同条「请确认」+「已全部收卷」→ finish_guard 回炉（无卡时 A∪C）。"""
    content = (
        "方向：先问你 / 关键缺口（调研对象未定）调研对象未明确——请确认：\n"
        "三路调研 + 独立审计已全部收卷，以下是决策简报。"
    )
    assert claims_needs_confirm(content)
    assert claims_full_delivery(content)
    rework = mutual_exclusion_rework(content)
    assert rework is not None
    assert "互斥" in rework
    reworks = finish_guard(content, citation_count=0)
    assert any("互斥" in r for r in reworks)


def test_e8fb470c_auc_same_message_flagged():
    """e8fb470c：同条「需要先确认关键信息」+「均已落盘」。"""
    content = (
        "调研可以并行展开，但需要先确认一个关键信息：**调研的对象是什么？**\n"
        "审计已完成，三份调研成稿均已落盘。"
    )
    reworks = finish_guard(content, citation_count=0)
    assert any("互斥" in r for r in reworks)


def test_auc_skipped_for_workers():
    content = "请确认调研对象。三路调研已全部收卷。"
    assert (
        finish_guard(content, citation_count=0, check_citations=False) == []
    )


def test_confirm_only_passes():
    assert mutual_exclusion_rework("需要先确认一个关键信息：调研对象是什么？") is None
    assert finish_guard("请确认后继续。", citation_count=0) == []


def test_delivery_only_passes_without_verdict():
    assert (
        mutual_exclusion_rework("三路调研 + 独立审计已全部收卷，以下是决策简报。")
        is None
    )


def test_reconcile_drops_confirm_pre_pause_when_new_delivers():
    """resume 拼接真源：C pre_pause ∪ A 续写 → 只保留续写。"""
    pre = "方向：先问你 / 关键缺口。调研对象未明确——请确认："
    new = "三路调研 + 独立审计已全部收卷，以下是决策简报。"
    assert reconcile_resume_closing(pre, new) == new


def test_reconcile_keeps_neutral_join():
    pre = "阶段成果如下：已整理竞品表。"
    new = "接下来补渠道策略一节。"
    out = reconcile_resume_closing(pre, new)
    assert "竞品表" in out
    assert "渠道策略" in out


def test_resume_continuity_steer_for_confirm_pre_pause():
    steer = resume_continuity_steer(
        prior_deliverable="需要先确认一个关键信息：调研对象是什么？"
    )
    assert "禁止" in steer
    assert "请确认" in steer
    assert "档位" in steer


def test_resume_continuity_steer_falls_back_for_deliverable():
    steer = resume_continuity_steer(prior_deliverable="已交付的前半段分析如下。")
    assert "自然衔接续写" in steer


def test_partial_verdict_rejects_posture_a():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("research/a.md",),
        execution_id="e1",
    )
    rework = closing_honesty_rework("三路调研已全部收卷。", verdict)
    assert rework is not None
    assert "档位" in rework
    assert "姿势 A" in rework
    reworks = finish_guard(
        "三路调研已全部收卷。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert any("姿势 A" in r or "档位" in r for r in reworks)


def test_partial_verdict_rejects_gathered_claim():
    """案面「已收齐」：partial/blocked/notes 时与收卷同属姿势 A。"""
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("research/a.md",),
        execution_id="e1",
    )
    for claim in (
        "三路调研已收齐，汇总如下。",
        "已全部收齐。",
        "全部收齐，以下是决策简报。",
        "已收齐。",
    ):
        assert claims_posture_a(claim), claim
        reworks = finish_guard(
            claim,
            citation_count=0,
            delivery_verdict=verdict,
        )
        assert any("姿势 A" in r or "档位" in r for r in reworks), claim


def test_notes_verdict_rejects_posture_a():
    """notes ≈ 草稿·部分：非正式完成，不得姿势 A。"""
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="notes",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    reworks = finish_guard(
        "全部完成，产物见工作区。",
        citation_count=0,
        delivery_verdict=verdict,
        overview_max_chars=1000,
    )
    assert any("姿势 A" in r or "档位" in r for r in reworks)


def test_gathered_auc_same_message_flagged():
    """「请确认」+「已收齐」同条 → 完成态互斥。"""
    content = (
        "方向：先问你 / 关键缺口（调研对象未定）调研对象未明确——请确认：\n"
        "三路调研已收齐，汇总如下。"
    )
    assert claims_posture_c(content)
    assert claims_posture_a(content)
    assert mutual_exclusion_rework(content) is not None
    reworks = finish_guard(content, citation_count=0)
    assert any("互斥" in r for r in reworks)


def test_bare_completed_not_posture_a():
    """修码/建站正常「已完成」不得误伤——裸「已完成」不进姿势 A 闭集。"""
    assert not claims_posture_a("修码已完成，详见 diff。")
    assert not claims_posture_a("站点已完成基础搭建。")
    assert not claims_posture_a("页面做好了，仍有缺口。")


def test_partial_requires_draft_acknowledgment_without_adding_completion_words():
    """evidence 降档（requires_draft_ack）时「综述已完成」不进姿势 A，缺承认 → 回炉。"""
    from agentcore.runtime.closing_posture import claims_draft_acknowledgment
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("AgentCore/文档/research/报告.md",),
        execution_id="e1",
        requires_draft_ack=True,
    )
    hollow = (
        "综述已完成。团队产出了一份 499 行、约 15,000 字的全面综述，"
        "结构如下。要我做下一步处理吗？"
    )
    assert not claims_posture_a(hollow)
    assert not claims_draft_acknowledgment(hollow)
    rework = closing_honesty_rework(hollow, verdict)
    assert rework is not None
    assert "承认" in rework or "缺口" in rework

    honest = (
        "先交一版草稿（证据不足）：缺参考文献列表，关键数据待核实。"
        "成稿见工作区；要我按审校意见补引用吗？"
    )
    assert claims_draft_acknowledgment(honest)
    assert closing_honesty_rework(honest, verdict) is None


def test_notes_without_posture_a_does_not_require_draft_ack():
    """notes 仅软提醒：无姿势 A 时不强制草稿承认句。"""
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="notes",
        delivered_files=("src/a.ts",),
        execution_id="e1",
    )
    assert (
        closing_honesty_rework("修码已完成，详见 diff；另有一处软提醒。", verdict)
        is None
    )


def test_ordinary_partial_without_draft_flag_allows_bare_delivered():
    """普通 partial（无 requires_draft_ack）不强制草稿承认——勿误伤建站裸「已交付」。"""
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("site/index.html",),
        execution_id="e1",
        requires_draft_ack=False,
    )
    assert closing_honesty_rework("主页已交付，详见产物卡。", verdict) is None
