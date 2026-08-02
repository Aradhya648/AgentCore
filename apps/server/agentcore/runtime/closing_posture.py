"""用户可见收口文案完成态互斥（交付诚实性）。

同一条用户可见收口消息只能落在其一：

- (A) 已交付完整结果
- (B) 部分完成并标明未完成项
- (C) 阻塞 / 需用户确认（不声称已交付）

禁止 A∪C，以及用「已完成 / 已全部收卷 / 已收齐」掩盖失败。本模块是姿势判定真源：
``finish_guard`` 拦单段正文自相矛盾；resume ``join`` 拦「请确认」pre_pause 与
「已全部收卷 / 已收齐」续写硬拼。
"""

from __future__ import annotations

import re

from agentcore.runtime.engine.segments import join_segments

# (A) 完整交付 / 全员收卷宣称（近零误报：显式完成话术，不含裸「已交付」）。
# 「已收齐」与「已全部收卷」同属案面全称收口（部分失败/薄交接不得用）。
_DELIVERED_CLAIMS = re.compile(
    r"(?:"
    r"已全部收卷|全部收卷|已收卷|"
    r"已全部收齐|全部收齐|已收齐|"
    r"已完成交付|交付已完成|完成交付|交付完成|已经交付完成|"
    r"已全部(?:完成|交付|就位|成功|就绪)|"
    r"全部(?:完成|交付|就位|成功|就绪)|"
    r"均已(?:完成|交付|就绪|成功|落盘)|"
    r"都已(?:完成|交付|就绪|成功)|"
    r"所有(?:任务|队员|节点)(?:已|都已)(?:完成|交付|就绪)|"
    r"(?:三路|各路|多路)?调研[^。\n]{0,24}(?:已全部收卷|已全部收齐|已收齐)|"
    r"审计已完成[^。\n]{0,40}均已落盘|"
    r"成稿均已落盘|"
    r"现在输出最终(?:决策)?简报|"
    r"(?:站点|网站|页面)[^。\n]{0,16}(?:做好了|已做好)"
    r")"
)

# (C) 需用户确认 / 关键缺口阻塞（不声称已交付）。
_NEEDS_CONFIRM_CLAIMS = re.compile(
    r"(?:"
    r"请确认|"
    r"需要先确认|"
    r"先确认(?:一个)?关键|"
    r"关键(?:信息|缺口|事实)(?:未定|未明确|未齐)|"
    r"关键缺口|"
    r"方向：先问你|"
    r"先问你\s*/\s*关键|"
    r"未明确——|"
    r"请直接告诉我你想要的交付形态"
    r")"
)

_GAP_NEGATION_PREFIXES = ("尚未", "没有", "并未", "未", "没", "无", "勿", "禁止", "不要")


def _positive_hits(pattern: re.Pattern[str], content: str) -> bool:
    """True when pattern matches a non-negated claim."""
    for match in pattern.finditer(content or ""):
        start = match.start()
        # 「已全部…」/「已完成交付」等以「已」开头的完成断言，自身即肯定。
        matched = match.group(0)
        if matched.startswith("已") or matched.startswith("全部") or matched.startswith("均已"):
            return True
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def claims_full_delivery(content: str) -> bool:
    """True when prose asserts full / rolled-up delivery (posture A)."""
    return _positive_hits(_DELIVERED_CLAIMS, content or "")


def claims_needs_confirm(content: str) -> bool:
    """True when prose asks the user to confirm a blocking gap (posture C)."""
    return _positive_hits(_NEEDS_CONFIRM_CLAIMS, content or "")


def mutual_exclusion_rework(content: str) -> str | None:
    """Return a finish_guard rework item when A and C co-occur in one message."""
    text = content or ""
    if not text.strip():
        return None
    if not (claims_full_delivery(text) and claims_needs_confirm(text)):
        return None
    return (
        "本条收口正文同时出现「需用户确认 / 关键缺口」与"
        "「已全部收卷 / 已收齐 / 已完成交付」类话术——"
        "完成态互斥：同一条用户可见收口只能是其一："
        "(A) 已交付完整结果；(B) 部分完成并标明未完成项；(C) 阻塞/需确认（不声称已交付）。"
        "请改写为单一姿势：若仍缺关键信息 → 只保留确认请求（可再调 ask_user），"
        "删除收卷/已收齐/已完成交付宣称；"
        "若已可交付 → 删除请确认/关键缺口话术，只写交付概览与缺口（有则标部分完成）。"
    )


def reconcile_resume_closing(pre_pause: str, new: str) -> str:
    """Join resume segments without creating A∪C across the pause seam.

    When pre-pause still carries「请确认」 framing (often leftover ask prose) and the
    post-resume segment claims full delivery, keep only the post-resume segment —
    the question already lived on the ask_user card; splicing recreates cef27dfa /
    e8fb470c dishonest closings.
    """
    left = pre_pause or ""
    right = new or ""
    if not left.strip():
        return right
    if not right.strip():
        return left
    if claims_needs_confirm(left) and claims_full_delivery(right):
        return right
    if claims_full_delivery(left) and claims_needs_confirm(right):
        # Rare: prior claimed done, resume asks again — prefer the later ask.
        return right
    return join_segments(left, right)


def resume_continuity_steer(*, prior_deliverable: str) -> str:
    """Steer the resumed CEO round; avoid amplifying stale confirm framing."""
    prior = (prior_deliverable or "").strip()
    if prior and claims_needs_confirm(prior) and not claims_full_delivery(prior):
        return (
            "[系统提示] 用户已通过确认卡作答。请基于用户答复推进下一步。"
            "【禁止】重复「请确认 / 关键缺口 / 先问你」话术；"
            "【禁止】在同一条收口里既要确认又宣称「已全部收卷 / 已收齐 / 已完成交付」。"
            "若关键信息仍缺 → 再次 ask_user（正文只保留确认，不写收卷/已收齐）；"
            "若已可收口 → 只写交付概览；有未完成项则标部分完成，勿假完成。"
        )
    from agentcore.runtime.engine.segments import deliverable_continuity_instruction

    return deliverable_continuity_instruction(prior_deliverable=prior_deliverable)
