"""调研/实务成篇质量策略（通用，非法务专用通道）。

定案：大纲按章落盘 / 空检索换策略 / research_report 强推 / 空 handoff 挡写作 /
成篇审计硬门 / 论文并行拆章须单主文件合并门禁。本模块只放纯谓词与文案常量，
供 playbook 声明、skill、检索预算、audit gate、delivery_status 复用——不新建子系统。

成篇硬审计**只认结构化**：``playbook=="research_report"``（入口另判）与
deliverable 结构字段（如 ``min_length≥3000``）。不扫 task/角色自由文猜意图。
"""

from __future__ import annotations

from typing import Any

from agentcore.workspace.stage_dirs import RESEARCH_DIR

# 论文/综述/长文成篇：允许并行拆章起草，但最终验收必须单一主文件（定案：
# 禁的是「并行拆章无合并门禁」，不是双文件本身；调研/代码/建站多产物不受本条约束）。
PAPER_PARALLEL_MERGE_DISCIPLINE = (
    "【论文/综述·单主文件门禁】允许并行拆章起草到临时路径，但最终交付验收必须是"
    "【同一主文件】；并行各章 brief 须写死同一目标路径 + 合并责任"
    "（末尾 merge worker，或 CEO 收口合并）。禁止各章各交各的当终稿。"
    "调研透镜 / 代码 / 建站等多产物场景不受本条约束。"
)

# research_report 默认成篇路径（可被 playbook_args.output_path 覆盖）。
DEFAULT_RESEARCH_REPORT_ARTIFACT = f"{RESEARCH_DIR}/报告.md"

# 本地改文件 / 广度摸底 / 成篇意图 / 字数承诺：用户·task 文 RE 猜意图腿已撤；
# team_gate 与成篇硬门不扫自由文分叉；选型靠提示词，硬门只认结构字段。

_REVIEW_ROLE_MARKERS = (
    "审校",
    "审计",
    "审查",
    "质检",
    "review",
    "audit",
)

# Playbook 显式声明上游 prose 地板时的默认值（如 repair_code 诊断员）。
# 不再作为「有下游 → 一律抬 min」的拓扑常量；交接地板只认 deliverable.min_length。
MIN_UPSTREAM_BODY_CHARS = 80

# 成篇门槛：派单时已知的 min_length（字）。≥ 此值视作成篇报告结构信号。
_LONG_FORM_MIN_LENGTH = 3_000


def has_landed_prose_artifact(kinds: object) -> bool:
    """True when this run already landed at least one ``prose`` artifact.

    Reads ``ToolContext.landed_artifact_kinds`` (shared mutable dict that survives
    ``dataclasses.replace``). Skeleton / empty landings do **not** count — only
    prose exempts the upstream body floor at handoff / executor completion.
    """
    if not isinstance(kinds, dict) or not kinds:
        return False
    return any(v == "prose" for v in kinds.values())


def upstream_body_floor_satisfied(
    *,
    body_chars: int,
    landed_artifact_kinds: object,
    min_body_chars: int = 0,
) -> bool:
    """Upstream floor from the same deliverable contract as ``check_contract``.

    ``min_body_chars`` = ``deliverable.min_length``（0 = 无字数地板）。已落盘 prose
    一律满足。无地板时：非空正文即视为可消费产出（拓扑仍靠
    ``handoff_requires_body`` 挡真正空交）；有地板时须 ``body ≥ min``。
    禁止再用全局 80 与 ``max_length`` 互殴。
    """
    if has_landed_prose_artifact(landed_artifact_kinds):
        return True
    floor = max(0, int(min_body_chars or 0))
    n = int(body_chars or 0)
    if floor <= 0:
        return n > 0
    return n >= floor


def batch_includes_review_role(tasks: object) -> bool:
    """True when hand-written tasks already include an independent review role."""
    if not isinstance(tasks, list):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        role = str(task.get("role") or "").strip().lower()
        if any(m in role for m in _REVIEW_ROLE_MARKERS):
            return True
    return False


def deliverable_signals_long_form(deliverable: Any) -> bool:
    """True when a deliverable dict/object signals long-form via structured fields."""
    if deliverable is None:
        return False
    if isinstance(deliverable, dict):
        min_length = int(deliverable.get("min_length") or 0)
    else:
        min_length = int(getattr(deliverable, "min_length", 0) or 0)
    return min_length >= _LONG_FORM_MIN_LENGTH


def plan_signals_long_form_audit(plan_nodes: object) -> bool:
    """True when any plan node deliverable has structured long-form signals.

    Does **not** scan free-text ``task`` / ``role`` for research/word-count intent.
    """
    if not isinstance(plan_nodes, (list, tuple)):
        return False
    for node in plan_nodes:
        deliverable = getattr(node, "deliverable", None)
        if deliverable is None and isinstance(node, dict):
            deliverable = node.get("deliverable")
        if deliverable_signals_long_form(deliverable):
            return True
    return False


def research_report_main_artifact(output_path: str | None = None) -> str:
    """Single main-file path for research_report acceptance (merge gate)."""
    cleaned = (output_path or "").strip().replace("\\", "/")
    if cleaned:
        return cleaned.lstrip("/")
    return DEFAULT_RESEARCH_REPORT_ARTIFACT
