"""完成态互斥（closing_posture）：A∪C 禁令 + resume 拼接真源。"""

from agentcore.runtime.closing_posture import (
    claims_full_delivery,
    claims_needs_confirm,
    mutual_exclusion_rework,
    reconcile_resume_closing,
    resume_continuity_steer,
)
from agentcore.runtime.verify import finish_guard


def test_cef27dfa_auc_same_message_flagged():
    """cef27dfa：同条「请确认」+「已全部收卷」→ finish_guard 回炉。"""
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
    """e8fb470c：同条「需要先确认关键信息」+「均已落盘 / 输出最终简报」。"""
    content = (
        "调研可以并行展开，但需要先确认一个关键信息：**调研的对象是什么？**\n"
        "审计已完成，三份调研成稿均已落盘。现在输出最终决策简报。"
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
    assert "已全部收卷" in steer
    assert "请确认" in steer


def test_resume_continuity_steer_falls_back_for_deliverable():
    steer = resume_continuity_steer(prior_deliverable="已交付的前半段分析如下。")
    assert "自然衔接续写" in steer


def test_partial_verdict_rejects_rolled_up_claim():
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

    verdict = DeliveryVerdict(
        state="partial",
        delivered_files=("research/a.md",),
        execution_id="e1",
    )
    reworks = finish_guard(
        "三路调研已全部收卷。",
        citation_count=0,
        delivery_verdict=verdict,
    )
    assert any("收卷" in r or "全部" in r or "交付完成" in r for r in reworks)
