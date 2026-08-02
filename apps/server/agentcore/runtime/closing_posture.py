"""用户可见收口诚实性：对账档位真源 + 极窄姿势探测。

真源是 ``delivery_verdict.state``（非完成话术词表）：

- ``delivered`` = 正式完成（允许姿势 A）
- ``partial`` / ``notes`` ≈ 草稿·部分（禁止姿势 A；``requires_draft_ack`` 时另须正文承认缺口）
- ``blocked`` = 阻塞（禁止姿势 A；``requires_draft_ack`` 时另须承认缺口）

姿势 A = 宣称完整交付 / 全员收卷 / 完整可用 / 修好验绿。
探测用**闭集**正则，仅作「是否在说 A」的薄信号；**禁止**靠案面加完成话术词修案。
文献证据降档时用正向「草稿/缺口承认」闭集（``requires_draft_ack``），不靠把「综述已完成」加进黑名单。
无对账卡时，仅拦同条正文 A∪C 自相矛盾（resume 拼接同理）。

``finish_guard`` / resume ``join`` / 确认姿势 steer 均消费本模块。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentcore.runtime.engine.segments import join_segments

if TYPE_CHECKING:
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

# 正式完成档（唯一允许姿势 A 的对账态）。
_FORMAL_COMPLETE_TIERS = frozenset({"delivered"})
# 非正式完成：草稿·部分·阻塞 —— 不得姿势 A。
_INFORMAL_TIERS = frozenset({"partial", "notes", "blocked"})

# (A) 完整交付宣称闭集。故意不含裸「已完成 / 已交付 / 弱可用」——修码/建站正常收口不得误伤。
# 禁止再往本表加案面词（「综述已完成」「站点做好了」等）；漏拦应回到档位/产物结构，而非加词。
_POSTURE_A_CLAIMS = re.compile(
    r"(?:"
    r"已全部收卷|全部收卷|已收卷|"
    r"已全部收齐|全部收齐|已收齐|"
    r"已完成交付|交付已完成|完成交付|交付完成|已经交付完成|"
    r"已全部(?:完成|交付|就位|成功|就绪)|"
    r"全部(?:完成|交付|就位|成功|就绪)|"
    r"均已(?:完成|交付|就绪|成功|落盘)|"
    r"都已(?:完成|交付|就绪|成功)|"
    r"所有(?:任务|队员|节点)(?:已|都已)(?:完成|交付|就绪)|"
    r"已完整可用|已可以使用|已经可以使用|"
    r"已完全可用|已可直接使用|已经可以直接使用|"
    r"已修好|修复已完成|bug\s*已修复|缺陷已修复|问题已修复|"
    r"已验证通过|验证通过|验证已绿|验证已通过|"
    r"测试已通过|已跑通测试|测试已跑通"
    r")"
)

# (C) 需用户确认 / 关键缺口阻塞——仅无档位时的 A∪C 与 resume 确认姿势用；保持极窄。
_POSTURE_C_CLAIMS = re.compile(
    r"(?:"
    r"请确认|"
    r"需要先确认|"
    r"先确认(?:一个)?关键|"
    r"关键(?:信息|缺口|事实)(?:未定|未明确|未齐)|"
    r"关键缺口|"
    r"方向：先问你|"
    r"先问你\s*/\s*关键|"
    r"未明确——"
    r")"
)

# partial/blocked 时正文须出现的「草稿/缺口承认」闭集（正向要求，不是完成话术黑名单）。
# 漏拦「综述已完成」等变体 → 扩本表或靠档位+承认，禁止往姿势 A 加案面词。
_DRAFT_ACK_CLAIMS = re.compile(
    r"(?:"
    r"草稿|"
    r"证据不足|证据不够|证据差|"
    r"部分完成|部分未完成|尚未完成|仍未完成|"
    r"未完成项|关键缺口|仍有缺口|存在缺口|"
    r"待补|待核实|待完善|需改进|"
    r"仅供参考|非正式(?:版|稿)|"
    r"未能(?:检索|完成|交付)|搜不到|"
    r"靠先验|基于先验|基于对该领域的了解"
    r")"
)

_GAP_NEGATION_PREFIXES = ("尚未", "没有", "并未", "未", "没", "无", "勿", "禁止", "不要")

_TIER_LABEL = {
    "blocked": "未满足/阻塞",
    "partial": "部分未满足",
    "notes": "草稿/备注",
}

# 硬降档（evidence_deficit → requires_draft_ack）时须承认缺口；普通 partial 不强制。
# （notes 仅软提醒，仍只拦姿势 A。）


def is_formal_complete_tier(state: str | None) -> bool:
    """True when delivery_verdict.state allows posture A (正式完成)."""
    return (state or "") in _FORMAL_COMPLETE_TIERS


def tier_forbids_posture_a(state: str | None) -> bool:
    """True when tier is partial/notes/blocked — posture A is dishonest."""
    return (state or "") in _INFORMAL_TIERS


def _positive_hits(pattern: re.Pattern[str], content: str) -> bool:
    """True when pattern matches a non-negated claim."""
    for match in pattern.finditer(content or ""):
        start = match.start()
        # Always honor negation prefixes（尚未全部完成 / 尚未完成交付…）——
        # even when the matched token itself starts with「全部/已」.
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def claims_posture_a(content: str) -> bool:
    """True when prose asserts formal-complete delivery (posture A). Closed set — do not expand."""
    return _positive_hits(_POSTURE_A_CLAIMS, content or "")


def claims_posture_c(content: str) -> bool:
    """True when prose asks the user to confirm a blocking gap (posture C)."""
    return _positive_hits(_POSTURE_C_CLAIMS, content or "")


def claims_draft_acknowledgment(content: str) -> bool:
    """True when prose acknowledges draft / gap / evidence shortfall (partial/blocked)."""
    return bool(_DRAFT_ACK_CLAIMS.search(content or ""))


# Resume / rehydrate 兼容别名（语义 = 姿势 A / C）。
claims_full_delivery = claims_posture_a
claims_needs_confirm = claims_posture_c


def closing_honesty_rework(
    content: str,
    delivery_verdict: DeliveryVerdict | None = None,
) -> str | None:
    """档位驱动的收口诚实性回炉项；无档位时退回薄 A∪C。

    主路径：``delivery_verdict.state`` ∉ 正式完成 → 不得姿势 A；
    ``requires_draft_ack``（文献证据降档）另须正文出现草稿/缺口承认（正向要求，不靠加完成词）。
    无对账卡：同条不得既 C 又 A（少靠双边大词表；C/A 均为闭集）。
    """
    text = content or ""
    if not text.strip():
        return None

    if delivery_verdict is not None:
        state = delivery_verdict.state
        if not tier_forbids_posture_a(state):
            return None
        label = _TIER_LABEL.get(state, state)
        if claims_posture_a(text):
            return (
                f"本回合交付对账档位为「{label}」（state={state}，见交付状态卡）——"
                "非正式完成档，正文不得姿势 A（宣称完整交付 / 全员收卷收齐 / "
                "已完整可用 / 已修好或验绿等）。"
                "请按档位改写：blocked → 承认阻塞与缺口；"
                "partial/notes → 标部分完成并点名未完成项；"
                "不要用完成话术盖过对账档位。"
                "真源=delivery_verdict 档位；禁止案面加完成话术词修案。"
            )
        if getattr(delivery_verdict, "requires_draft_ack", False) and not claims_draft_acknowledgment(
            text
        ):
            return (
                f"本回合交付对账档位为「{label}」（state={state}，证据降档）——"
                "正文须在开场承认草稿/部分完成/证据不足或点名未完成项，"
                "不得仅用字数或「已完成」叙事冒充正式交付。"
                "请把缺口写在最前面；真源=对账档位，禁止靠加完成话术词修案。"
            )
        return None

    # 无对账卡：仅拦同条 A∪C 自相矛盾。
    if not (claims_posture_a(text) and claims_posture_c(text)):
        return None
    return (
        "本条收口正文同时出现「需用户确认 / 关键缺口」（姿势 C）与"
        "「完整交付 / 收卷收齐 / 验绿」类宣称（姿势 A）——"
        "完成态互斥：同一条用户可见收口只能是其一："
        "(A) 已交付完整结果；(B) 部分完成并标明未完成项；(C) 阻塞/需确认（不声称已交付）。"
        "请改写为单一姿势：若仍缺关键信息 → 只保留确认请求（可再调 ask_user），"
        "删除收卷/已收齐/完整交付宣称；"
        "若已可交付 → 删除请确认/关键缺口话术，只写交付概览与缺口（有则标部分完成）。"
    )


def mutual_exclusion_rework(content: str) -> str | None:
    """无档位时的 A∪C 互斥（兼容旧调用）；有档位请用 :func:`closing_honesty_rework`。"""
    return closing_honesty_rework(content, delivery_verdict=None)


def reconcile_resume_closing(pre_pause: str, new: str) -> str:
    """Join resume segments without creating A∪C across the pause seam.

    When pre-pause still carries「请确认」 framing (often leftover ask prose) and the
    post-resume segment claims posture A, keep only the post-resume segment —
    the question already lived on the ask_user card; splicing recreates cef27dfa /
    e8fb470c dishonest closings.
    """
    left = pre_pause or ""
    right = new or ""
    if not left.strip():
        return right
    if not right.strip():
        return left
    if claims_posture_c(left) and claims_posture_a(right):
        return right
    if claims_posture_a(left) and claims_posture_c(right):
        # Rare: prior claimed done, resume asks again — prefer the later ask.
        return right
    return join_segments(left, right)


def resume_continuity_steer(*, prior_deliverable: str) -> str:
    """Steer the resumed CEO round; avoid amplifying stale confirm framing."""
    prior = (prior_deliverable or "").strip()
    if prior and claims_posture_c(prior) and not claims_posture_a(prior):
        return (
            "[系统提示] 用户已通过确认卡作答。请基于用户答复推进下一步。"
            "【禁止】重复「请确认 / 关键缺口 / 先问你」话术；"
            "【禁止】在同一条收口里既要确认又宣称完整交付 / 收卷收齐。"
            "若关键信息仍缺 → 再次 ask_user（正文只保留确认，不写收卷/已收齐）；"
            "若已可收口 → 只写交付概览；有未完成项则标部分完成，勿假完成。"
            "有交付对账卡时以档位为准（delivered=正式完成；否则不得姿势 A）。"
        )
    from agentcore.runtime.engine.segments import deliverable_continuity_instruction

    return deliverable_continuity_instruction(prior_deliverable=prior_deliverable)
