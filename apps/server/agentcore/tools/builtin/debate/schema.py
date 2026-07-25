"""debate tool schema + argument parsing（薄适配层；域常量见 runtime.debate.constants）。"""

from __future__ import annotations

import re
from typing import Any

from agentcore.runtime.debate import DebateForm, DebateSide
from agentcore.runtime.debate.constants import (
    CLOSING_LENGTH_HINT,
    CX_LENGTH_HINT,
    DEBATE_FORM_VALUES,
    DEBATE_OUTPUT_LIMIT,
    DEBATER_TOOLS,
    FORM_LABELS,
    LENGTH_HINT,
    QUICK_DEBATER_HINT,
)
from agentcore.tools.protocol import ToolResult

__all__ = [
    "DEBATE_OUTPUT_LIMIT",
    "DEBATER_TOOLS",
    "LENGTH_HINT",
    "CLOSING_LENGTH_HINT",
    "CX_LENGTH_HINT",
    "QUICK_DEBATER_HINT",
    "FORM_LABELS",
    "DEBATE_DESCRIPTION",
    "DEBATE_PARAMETERS",
    "STANCE_MAX_CHARS",
    "err",
    "parse_form",
    "parse_background",
    "parse_sides",
    "validate_stance",
]

# 薄立场兜底硬上限：真意图是「一句立场倾向、不带论证」（语义形状），不是字符数。
# 48 字闸三次被 LLM 突破致 debate 首调失败——放宽到 80 作兜底，主拦靠形状校验。
STANCE_MAX_CHARS = 80

# 语义形状违规（机械可查，任一命中即拒）：换行、分号、编号/顿号列表、论证展开标记、
# 以及把辩手当执行器的论点清单 / 剧本指令措辞。
_STANCE_LIST_MARKERS = re.compile(
    r"(?:\([1-9]\)|（[1-9]）|[①②③④⑤⑥⑦⑧⑨]|"
    r"(?:^|[\s；;。，,])[1-9][\.、]|"
    r"(?:^|[\s；;。，,])[一二三四五六七八九十][、.])"
)
_STANCE_ARGUMENT_MARKERS = re.compile(
    r"首先|其次|再次|最后|其一|其二|其三|一是|二是|三是|"
    r"一方面|另一方面|综上|总而言之"
)
_STANCE_SCRIPT_CUES = re.compile(
    r"核心论点|论点包括|请从.{0,16}角度|系统论证|论证角度|"
    r"重点论证|分点论证|依次论证|论证路径|请论证|务必论证"
)

_STANCE_RETRY_TIP = (
    "薄立场硬校验未通过：`stance` 只写【一句】该方主张什么结论的立场倾向。"
    "正例：「支持一审判决正确」/「认为判赔过重」。"
    "须为单句判断句；禁换行、分号、编号/顿号列表、"
    "「首先/其次/一、二、」类论证展开，亦禁论点清单与论证角度指令——"
    "客观事实归 `background`，论点与论证路径由辩手自己检索构建。"
    "请改写成一句立场倾向后重试本工具。"
)

# Schema layer (工具面瘦身): short trigger + key param cues. HOW → debate_and_review skill.
DEBATE_DESCRIPTION = (
    "对需要【对抗性多视角思考】的问题发起主持人驱动的结构化辩论，交回【决策简报 + 交锋叙事线】"
    "双产物（非终结，产物回到你的循环）。"
    "form：debate=正反决策；red_team=红队压测方案（被审方标 is_subject）；roundtable=圆桌观点光谱。"
    "传 motion + form + sides（≥2）；轮数与收敛由主持人自调。"
    "各角度独立的并行调研用 delegate；无对立面 / 单点事实不要用本工具。"
    "细节见 consult_skill(debate_and_review)。"
)

DEBATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "motion": {
            "type": "string",
            "description": "辩论命题（用户原话或你提炼的争议命题）。",
        },
        "form": {
            "type": "string",
            "enum": list(DEBATE_FORM_VALUES),
            "description": (
                "debate=正反攻防（并行波+质询+结辩）；"
                "red_team=红队挑刺（finding 台账+攻→应→复三拍+门决；被审方标 is_subject）；"
                "roundtable=多方圆桌（分题点名串行线程+共识/分歧地图）。"
            ),
        },
        "sides": {
            "type": "array",
            "description": "参与方（≥2）：正反=2，圆桌≥3，红队=被审方 + ≥1 红队。",
            "items": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "机器标识（唯一英文短词，如 pro/con/red1）。",
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "展示名：简短的立场 / 视角名，各方对称同风格；勿塞模型名"
                            "（模型走 model 字段）。"
                        ),
                    },
                    "stance": {
                        "type": "string",
                        # 生成侧兜底：maxLength 拦极端超长；真意图靠 validate_stance 语义形状。
                        "maxLength": STANCE_MAX_CHARS,
                        "description": (
                            f"一句话立场倾向（单句判断句；硬上限 {STANCE_MAX_CHARS} 字作兜底）："
                            "只说该方主张什么结论"
                            "（正例：「支持一审判决正确」/「认为判赔过重」）；"
                            "禁换行、分号、编号列表、「首先/其次」类论证展开、"
                            "论点清单与论证角度指令、事实细节——"
                            "客观事实归 background，论点与论证路径归辩手自己检索构建。"
                            "反例（勿写，会被拒）：「核心论点包括(1)…(4)；请从…角度系统论证」。"
                        ),
                    },
                    "is_subject": {
                        "type": "boolean",
                        "description": "仅红队形态：标记被审的方案方。",
                    },
                    "model": {
                        "type": "string",
                        "description": "（可选·MVP 未启用）per-side 模型覆写预留；请留空。",
                    },
                },
                "required": ["key", "name", "stance"],
            },
        },
        "thorough": {
            "type": "boolean",
            "description": (
                "默认 true=辩透（主持人自判收敛）；false=快速单轮对碰（用户只想轻量看看时）。"
            ),
        },
        "background": {
            "type": "string",
            "description": (
                "（可选）赛前底料：已核实客观事实清单，每条须附【来源】与【日期】；"
                "未决 / 推断不得写成既定事实；只放事实不放观点。纯价值观命题不必传。"
                "格式与硬化禁令见 debate_and_review。"
            ),
        },
    },
    "required": ["motion", "form", "sides"],
}


def err(msg: str) -> ToolResult:
    return ToolResult(tool_call_id="", success=False, output=msg, error=msg)


def parse_form(raw: Any) -> DebateForm:
    if isinstance(raw, str):
        try:
            return DebateForm(raw.strip())
        except ValueError:
            pass
    return DebateForm.DEBATE


def parse_background(raw: Any) -> str:
    """解析可选案件底料；仅收非空字符串，其它类型 / 缺省 → 空串（零行为变化路径）。"""
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def validate_stance(stance: str, *, side_key: str = "") -> str | None:
    """薄立场硬校验。返回错误信息（含重试引导），或 None 表示通过。

    对齐 ``validate_search_query``：只拒不改写。真意图是单句立场倾向（不带论证）；
    机械拦换行 / 分号 / 编号列表 / 「首先其次」类展开与论点清单特征；
    :data:`STANCE_MAX_CHARS` 仅作兜底字数闸。
    """
    text = (stance or "").strip()
    if not text:
        return None
    where = f"sides[`{side_key}`].stance" if side_key else "stance"
    n = len(text)
    if n > STANCE_MAX_CHARS:
        return (
            f"{where} 过长（{n} 字，硬上限 {STANCE_MAX_CHARS}）。{_STANCE_RETRY_TIP}"
        )
    if "\n" in text or "\r" in text:
        return f"{where} 含换行，非单句立场形状。{_STANCE_RETRY_TIP}"
    if ";" in text or "；" in text:
        return f"{where} 含分号，非单句立场形状。{_STANCE_RETRY_TIP}"
    if (
        _STANCE_LIST_MARKERS.search(text)
        or _STANCE_ARGUMENT_MARKERS.search(text)
        or _STANCE_SCRIPT_CUES.search(text)
    ):
        return f"{where} 含论点清单/论证展开特征。{_STANCE_RETRY_TIP}"
    return None


def parse_sides(raw: Any) -> tuple[list[DebateSide], str]:
    """把 sides 原始数组解析为 :class:`DebateSide` 列表；返回 (sides, 错误信息)。"""
    if not isinstance(raw, list) or len(raw) < 2:
        return [], "debate 需要 sides（参与方数组，至少 2 个，每个含 key/name/stance）。"
    sides: list[DebateSide] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        name = str(item.get("name") or "").strip()
        stance = str(item.get("stance") or "").strip()
        if not key or not name or not stance:
            continue
        if key in seen:
            return [], f"sides 的 key 重复：`{key}`（每个参与方需唯一 key）。"
        stance_err = validate_stance(stance, side_key=key)
        if stance_err:
            return [], stance_err
        seen.add(key)
        # model（可选）：Phase 3 真·多模型辩手预留，宽松解析（仅收非空字符串）；MVP 不注入执行。
        model = str(item.get("model") or "").strip()
        sides.append(
            DebateSide(
                key=key,
                name=name,
                stance=stance,
                is_subject=bool(item.get("is_subject")),
                model=model,
            )
        )
    if len(sides) < 2:
        return [], "debate 至少需要 2 个有效参与方（每个含非空 key/name/stance）。"
    return sides, ""
