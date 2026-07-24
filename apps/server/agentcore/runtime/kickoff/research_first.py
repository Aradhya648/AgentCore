"""辩论开工卡「先多视角调研再辩」— 判据与回灌文案。

⏳ 2026-07-21 定案：开工卡 ``research_first`` 按键退役（庭前取证内化为辩论固有阶段）。
``should_offer_research_first`` / ``should_recommend_research_first`` 恒 False；
回灌文案与 resume 分支保留（旧 journal / 阶段推进卡 ``research_first`` decision 仍合法）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentcore.memory.followups import select_motion_card_from_journal
from agentcore.runtime.skills import MULTI_LENS_COURTROOM_TRIGGERS

_MLR_PLAYBOOK = "multi_lens_research"

# 回灌文案定稿骨架（命令式、唯一合法下一步）。topic 由 motion / 用户原话填充。
RESEARCH_FIRST_RESULT_SKELETON = (
    "用户在开赛确认中选择「先多视角调研再辩」。本场辩论未授权，请勿再次调用 debate。"
    "本回合必须立即调用 delegate(playbook=\"multi_lens_research\", "
    "playbook_args.topic 从挂起的 debate motion 或用户原话取)；"
    "调研与呈报完成、用户拍板后再开辩。"
)


def should_offer_research_first(
    entries: Sequence[Mapping[str, Any]] | None,
    *,
    has_research_artifacts: bool = False,
) -> bool:
    """开工卡是否提供「先多视角调研再辩」——定案退役后恒 False。

    旧判据（命题卡 / MLR 成功 / 案卷产物并集消假阳性）保留为
    :func:`has_research_chain_evidence` 供宿主挂接探测。
    """
    del entries, has_research_artifacts  # 退役：不再点亮按键
    return False


def has_research_chain_evidence(
    entries: Sequence[Mapping[str, Any]] | None,
    *,
    has_research_artifacts: bool = False,
) -> bool:
    """是否已有调研链证据（命题卡 / MLR / 案卷）——原 offer 判据的逆命题素材。"""
    if select_motion_card_from_journal(entries) is not None:
        return True
    if _has_successful_multi_lens_research(entries):
        return True
    return bool(has_research_artifacts)


def hits_multi_lens_courtroom_triggers(user_message: str) -> bool:
    """用户本回合输入是否命中多维取证类终局对抗触发词。

    词表同源 :data:`agentcore.runtime.skills.MULTI_LENS_COURTROOM_TRIGGERS`。
    """
    text = (user_message or "").strip()
    if not text:
        return False
    return any(trigger in text for trigger in MULTI_LENS_COURTROOM_TRIGGERS)


def should_recommend_research_first(
    entries: Sequence[Mapping[str, Any]] | None,
    *,
    has_research_artifacts: bool = False,
    user_message: str = "",
) -> bool:
    """开工卡主键推荐——定案退役后恒 False。"""
    del entries, has_research_artifacts, user_message
    return False


def research_first_tool_result(*, motion: str = "", user_message: str = "") -> str:
    """``research_first`` 决议的固定回灌文案（topic 取 motion，否则用户原话）。"""
    topic = (motion or "").strip() or (user_message or "").strip() or "（从用户原话提炼主题）"
    # Strip quotes so the imperative blob stays a single readable command line.
    topic = topic.replace('"', "'")
    return (
        "用户在开赛确认中选择「先多视角调研再辩」。本场辩论未授权，请勿再次调用 debate。"
        f'本回合必须立即调用 delegate(playbook="multi_lens_research", '
        f'playbook_args={{"topic": "{topic}"}})；调研与呈报完成、用户拍板后再开辩。'
    )


def _has_successful_multi_lens_research(
    entries: Sequence[Mapping[str, Any]] | None,
) -> bool:
    if not entries:
        return False
    # tool_call facts are the authoritative completed-call record (success + args).
    for entry in entries:
        kind = str(entry.get("kind") or entry.get("type") or "")
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if kind != "tool_call":
            continue
        if str(payload.get("name") or "") != "delegate":
            continue
        if payload.get("success") is False:
            continue
        if _args_playbook_is_mlr(payload.get("arguments")):
            return True
    # Fallback: tool_use_start (playbook) paired with successful tool_use_end.
    mlr_ids: set[str] = set()
    for entry in entries:
        kind = str(entry.get("kind") or entry.get("type") or "")
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if kind == "tool_use_start" and str(payload.get("name") or "") == "delegate":
            if _args_playbook_is_mlr(payload.get("arguments")):
                tid = str(payload.get("tool_call_id") or payload.get("id") or "")
                if tid:
                    mlr_ids.add(tid)
        elif kind == "tool_use_end" and payload.get("success") is not False:
            tid = str(payload.get("tool_call_id") or payload.get("id") or "")
            if tid and tid in mlr_ids:
                return True
    return False


def _args_playbook_is_mlr(raw: Any) -> bool:
    if isinstance(raw, Mapping):
        return str(raw.get("playbook") or "") == _MLR_PLAYBOOK
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return _MLR_PLAYBOOK in raw
        if isinstance(parsed, Mapping):
            return str(parsed.get("playbook") or "") == _MLR_PLAYBOOK
    return False
