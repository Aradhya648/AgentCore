"""MAST 失败标签（学·度量 §2.5：评测集的失败标准词）.

直接采用 **MAST**（Multi-Agent System Failure Taxonomy，Cemri et al. 2025；1600+ 真实
轨迹归纳的 14 类失败、三大组）作为离线多 Agent 评测集的**失败标签**——不自创一套词。每条
黄金用例用 ``mast`` 字段挂一个失败模式码（如 ``"1.3"``），report 据此**按 MAST 类 / 组
聚合通过率**，使「拆·lead 下放 / 合·验证两道 到底有没有压低某类失败」从拍脑袋变成可量化
对照（也是 B 默认铺开的数据闸门）。

纯静态（仅 dataclass + 常量 + 校验），不 import runtime/LLM，故 ``seed_lint`` / ``__init__``
复用零负担、不被 pipeline/engine 拖下水。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MastMode:
    """一个 MAST 失败模式：码 + 所属组 + 中英标签。"""

    code: str
    group: str
    en: str
    zh: str


# 三大组（MAST 顶层归并）：组码 → (英文, 中文)。
MAST_GROUPS: dict[str, tuple[str, str]] = {
    "FC1": ("Specification & System Design", "规格不达"),
    "FC2": ("Inter-Agent Misalignment", "互相错位"),
    "FC3": ("Task Verification & Termination", "验证缺位"),
}

# 14 类失败模式（键 = 码 ``g.i``：g=组序 1/2/3、i=组内序）。与 MAST 论文逐条对齐。
MAST_MODES: dict[str, MastMode] = {
    m.code: m
    for m in (
        # ── FC1 规格不达 ──
        MastMode("1.1", "FC1", "Disobey task specification", "不遵守任务规格"),
        MastMode("1.2", "FC1", "Disobey role specification", "不遵守角色规格"),
        MastMode("1.3", "FC1", "Step repetition", "步骤重复"),
        MastMode("1.4", "FC1", "Loss of conversation history", "丢失对话历史"),
        MastMode("1.5", "FC1", "Unaware of termination conditions", "不认终止条件"),
        # ── FC2 互相错位 ──
        MastMode("2.1", "FC2", "Conversation reset", "对话被重置"),
        MastMode("2.2", "FC2", "Fail to ask for clarification", "该问不问"),
        MastMode("2.3", "FC2", "Task derailment", "任务跑偏"),
        MastMode("2.4", "FC2", "Information withholding", "信息藏着不说"),
        MastMode("2.5", "FC2", "Ignored other agent's input", "无视他人产出"),
        MastMode("2.6", "FC2", "Reasoning-action mismatch", "想得对做得错"),
        # ── FC3 验证缺位 ──
        MastMode("3.1", "FC3", "Premature termination", "过早终止"),
        MastMode("3.2", "FC3", "No or incomplete verification", "验证缺失/不全"),
        MastMode("3.3", "FC3", "Incorrect verification", "验证做错"),
    )
}

MAST_CODES = frozenset(MAST_MODES)


def is_valid_mast_code(code: str) -> bool:
    """``code`` 是否为已知的 14 类之一。"""
    return code in MAST_MODES


def group_of(code: str) -> str | None:
    """码 → 组（FC1/FC2/FC3）；未知码返回 ``None``。"""
    mode = MAST_MODES.get(code)
    return mode.group if mode else None


def label_of(code: str) -> str:
    """码 → 人读标签 ``"1.3 步骤重复"``；未知码原样返回。"""
    mode = MAST_MODES.get(code)
    return f"{mode.code} {mode.zh}" if mode else code
