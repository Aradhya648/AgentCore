"""Consumer-missing-depends gate: task 写明吃同批队友产出但 depends_on 为空 → 结构化拒绝.

产品判据：同批 ≥2 tasks 时，文案明确要吃队友 / 上游产出却漏声明边 → 拒收入图并给可改边纠错。
判定只看「是否吃同批上游」cue，不按职位名一刀切；``force=true`` 可旁路。
引擎不猜边、不自动改图——只拒收。
"""

from __future__ import annotations

import re
from typing import Any

# 对齐 skill「生产者→消费者」：仅队友 / 同批上游指称，勿误伤「基于公开报告」等外部材料。
_CONSUMER_CUE = re.compile(
    r"基于(?:前|上述|以上)"
    r"|基于[^。；;\n]{0,40}(?:队员|队友|上游)[^。；;\n]{0,20}产出"
    r"|(?:综合|汇总)[^。；;\n]{0,20}(?:前|上述|以上)"
    r"|上游产出|吃上游"
    r"|based\s+on\s+(?:previous|above|both|other)",
    re.IGNORECASE,
)


def task_claims_teammate_output(task_text: str) -> bool:
    """True when task 文案明确要吃同批队友 / 上游产出（非外部公开材料）。"""
    text = (task_text or "").strip()
    if not text:
        return False
    return _CONSUMER_CUE.search(text) is not None


def _depends_empty(task: dict[str, Any]) -> bool:
    """缺失 / ``[]`` / ``null`` 都算空；非空列表放行。"""
    deps = task.get("depends_on")
    if deps is None:
        return True
    if isinstance(deps, list):
        return len(deps) == 0
    # 非列表且假值（如 ""）视为空；真值保守放行，交给后续建图校验。
    return not deps


def _peer_ref(task: dict[str, Any]) -> str:
    tid = task.get("id")
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    role = task.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip()
    return ""


def consumer_missing_depends_reject_message(
    *,
    violators: list[dict[str, Any]],
    peers: list[str],
) -> str:
    roles = "、".join(
        f"「{(v.get('role') or v.get('id') or '?')}」" for v in violators
    )
    if peers:
        cited = "、".join(peers)
        example = "[" + ", ".join(f'"{p}"' for p in peers) + "]"
        dep_hint = (
            f"请将同批其它任务的 id（无则 role）写入 `depends_on`"
            f"（建议引用：{cited}，例如 `depends_on: {example}`）"
        )
    else:
        dep_hint = "请将同批其它任务的 id（无则 role）写入 `depends_on`"
    return (
        f"{roles}的 task 写明要吃同批队友产出，但 `depends_on` 为空——"
        f"{dep_hint}；"
        "若本就独立，请改文案去掉依赖表述，或显式传 `force=true` 旁路。"
    )


def check_consumer_missing_depends(
    tasks: list[Any],
    *,
    force: bool = False,
) -> str | None:
    """同批消费者漏边时返回拒绝文案；否则 None。"""
    if force is True:
        return None
    if not isinstance(tasks, list) or len(tasks) < 2:
        return None

    dict_tasks = [t for t in tasks if isinstance(t, dict)]
    if len(dict_tasks) < 2:
        return None

    violators: list[dict[str, Any]] = []
    for task in dict_tasks:
        if not _depends_empty(task):
            continue
        raw = task.get("task") or ""
        text = raw if isinstance(raw, str) else str(raw)
        if task_claims_teammate_output(text):
            violators.append(task)

    if not violators:
        return None

    violator_ids = {id(v) for v in violators}
    peers: list[str] = []
    seen: set[str] = set()
    for task in dict_tasks:
        if id(task) in violator_ids:
            continue
        ref = _peer_ref(task)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        peers.append(ref)

    return consumer_missing_depends_reject_message(
        violators=violators,
        peers=peers,
    )
