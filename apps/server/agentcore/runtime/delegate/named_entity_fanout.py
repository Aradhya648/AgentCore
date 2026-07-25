"""Named-entity compare fanout gate: 点名 N 实体对比却 tasks 人数不足 → 结构化拒绝.

产品判据：用户点名 ≥2 个并列对比对象时，手写 ``tasks`` 至少每实体一员并行。
提示词多次被模型合理化绕开后，在 ``delegate`` 入口做窄硬闸（``force=true`` 可旁路）。

只看用户原话里的点名列表；无点名（如「市面三款」未列品牌）不触发。
playbook 展开路径不走本闸（形状由 playbook 负责）。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 对比 / 选型意图（窄）：避免普通「和」连接句误触。
_COMPARE_CUE = re.compile(r"(系统对比|横向对比|分别评估|对比|比较|选型)")

# 从「对比/分别评估 …」后截到边界，再按顿号等切开。
_LIST_SPAN = re.compile(
    r"(?:系统对比|横向对比|分别评估|对比|比较)\s*"
    r"(.+?)"
    r"(?:三者|二者|几者|之间|\s+在|的取舍|，再|再汇总|（|\(|$)",
)

_SPLIT = re.compile(r"[、,/]|与|和|以及")

# 维度词 / 空话：不当成对比实体。
_STOP = frozenset(
    {
        "性能",
        "运维",
        "生态",
        "适用场景",
        "上手成本",
        "长期维护",
        "定价",
        "功能",
        "优缺点",
        "取舍",
        "角度",
        "维度",
        "方面",
        "中小型",
        "项目",
        "内部工具",
        "前端栈",
        "数据库",
    }
)


def extract_named_compare_entities(user_message: str) -> list[str]:
    """从用户话里抽出点名的并列对比实体；无对比意图或抽不出 → 空列表。"""
    text = (user_message or "").strip()
    if not text or not _COMPARE_CUE.search(text):
        return []
    match = _LIST_SPAN.search(text)
    if not match:
        return []
    span = match.group(1).strip().strip("「」『』\"'")
    # 去掉尾部残留连接词
    span = re.sub(r"(三者|二者|几者)$", "", span).strip()
    entities: list[str] = []
    seen: set[str] = set()
    for raw in _SPLIT.split(span):
        name = raw.strip().strip("「」『』\"'“”")
        if not name or len(name) > 40:
            continue
        if name in _STOP or name.lower() in {s.lower() for s in _STOP}:
            continue
        # 单字中文多半是噪声；英文缩写（如 Go）放行
        if len(name) < 2 and not name.isascii():
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        entities.append(name)
    return entities if len(entities) >= 2 else []


def named_entity_fanout_reject_message(
    *,
    entities: list[str],
    task_count: int,
) -> str:
    n = len(entities)
    listed = "、".join(entities)
    return (
        f"用户点名对比 {n} 个并列实体（{listed}），本次 `tasks` 只有 {task_count} 人——"
        f"须至少派 {n} 人（每实体一员并行，可另加 1 名汇总），禁止 1 人包办整场对比。"
        "请按实体拆开重派；若确需少派，显式传 `force=true` 并说明理由。"
    )


def check_named_entity_fanout(
    arguments: dict[str, Any],
    *,
    user_message: str,
) -> str | None:
    """手写 tasks 少派时返回拒绝文案；否则 None。

    跳过：playbook 展开、``force=true``、跨图 append、抽不出点名实体。
    """
    if arguments.get("force") is True:
        return None
    if arguments.get("playbook") or arguments.get("playbook_id"):
        pid = arguments.get("playbook_id") or arguments.get("playbook")
        if pid and pid != "none":
            return None
    if arguments.get("append_to_execution_id"):
        return None
    tasks = arguments.get("tasks")
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except json.JSONDecodeError:
            tasks = None
    if not isinstance(tasks, list) or not tasks:
        return None
    entities = extract_named_compare_entities(user_message)
    if not entities:
        return None
    if len(tasks) >= len(entities):
        return None
    return named_entity_fanout_reject_message(
        entities=entities,
        task_count=len(tasks),
    )
