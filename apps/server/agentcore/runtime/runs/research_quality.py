"""调研/实务成篇质量策略（通用，非法务专用通道）。

定案：大纲按章落盘 / 空检索换策略 / research_report 强推 / 空 handoff 挡写作 /
成篇审计硬门 / 论文并行拆章须单主文件合并门禁。本模块只放纯谓词与文案常量，
供 playbook 声明、skill、检索预算、audit gate、delivery_status 复用——不新建子系统。
"""

from __future__ import annotations

import re
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

# 成篇意图：调研/实务报告 + 成文/字数承诺（与建站意图正交）。
# 亦覆盖「点名多对象对比 + Markdown/落盘」（竞品对比表等）——team_gate 硬收依赖本谓词。
_RESEARCH_REPORT_INTENT_RE = re.compile(
    r"(?:"
    r"(?:调研|研究|实务|研究报告|调研报告|分析报告|成篇|成文|写一篇|撰写)"
    r".{0,24}"
    r"(?:报告|文档|文章|材料|成篇|成文|论文)"
    r"|"
    r"(?:写|撰写|完成|交付).{0,16}(?:报告|实务|调研|论文)"
    r"|"
    r"(?:论文研究|研究论文|学术论文|写.{0,24}论文)"
    r"|"
    r"(?:research\s+report|write\s+(?:a\s+)?(?:report|brief|paper|thesis))"
    r"|"
    r"(?:调研|对比|比较).{0,96}(?:落盘|Markdown|\.md\b|对比表)"
    r"|"
    r"(?:整理成|写成|输出).{0,40}(?:对比表|对比报告)"
    r")",
    re.IGNORECASE,
)

# 本地改文件意图：允许极少次 file_list/file_read/grep 摸仓，再催派（与网页独搜分闸）。
_LOCAL_FILE_EDIT_INTENT_RE = re.compile(
    r"(?:"
    r"(?:改|修改|编辑|更新).{0,48}"
    r"(?:README|\.md\b|\.py\b|\.ya?ml\b|\.json\b|\.ts\b|\.tsx\b|\.js\b|\.toml\b|文件|配置)"
    r"|"
    r"(?:在|往).{0,24}(?:README|\.md\b).{0,24}(?:加|加一小节|加上|添加)"
    r"|"
    r"(?:把|将).{0,48}(?:改成|改为).{0,24}(?:,|，|。|$)"
    r"|"
    r"(?:只改这一行|其余内容别动|别动别的)"
    r")",
    re.IGNORECASE,
)

# 明确字数承诺（如 5000–8000 字 / 不少于三千字）。
_WORD_COUNT_COMMIT_RE = re.compile(
    r"(?:"
    r"\d{3,5}\s*[–\-~到至]\s*\d{3,5}\s*字"
    r"|"
    r"(?:约|大约|不少于|至少|超过)?\s*\d{4,5}\s*字"
    r"|"
    r"(?:min_length|字数).{0,8}\d{4,5}"
    r")",
    re.IGNORECASE,
)

_REVIEW_ROLE_MARKERS = (
    "审校",
    "审计",
    "审查",
    "质检",
    "review",
    "audit",
)

# handoff：有下游时正文地板（chars）；与 MIN_HANDOFF_SUMMARY 正交。
MIN_UPSTREAM_BODY_CHARS = 80


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
) -> bool:
    """Upstream deliverable floor: enough streamed prose, or a landed prose file."""
    if int(body_chars or 0) >= MIN_UPSTREAM_BODY_CHARS:
        return True
    return has_landed_prose_artifact(landed_artifact_kinds)


def is_research_report_intent(*texts: str) -> bool:
    """True when text asks for a research / practical long-form write-up.

    Includes multi-object compare + Markdown/落盘 deliverables (e.g. competitor
    tables). Local file tweaks (README 改一小节) must stay False — those use
    :func:`is_local_file_edit_intent` for the lighter team_gate path.
    """
    blob = " ".join(t for t in texts if isinstance(t, str) and t.strip())
    if not blob:
        return False
    return bool(_RESEARCH_REPORT_INTENT_RE.search(blob))


def is_local_file_edit_intent(*texts: str) -> bool:
    """True when text asks to edit an existing workspace file (light local recon).

    Orthogonal to :func:`is_research_report_intent`: research/compare-deliverable
    wins so「调研+落盘」never takes the README-style local gate.
    """
    blob = " ".join(t for t in texts if isinstance(t, str) and t.strip())
    if not blob:
        return False
    if is_research_report_intent(blob):
        return False
    return bool(_LOCAL_FILE_EDIT_INTENT_RE.search(blob))


def has_word_count_commitment(*texts: str) -> bool:
    """True when text commits to an explicit long-form length."""
    blob = " ".join(t for t in texts if isinstance(t, str) and t.strip())
    if not blob:
        return False
    return bool(_WORD_COUNT_COMMIT_RE.search(blob))


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
    """True when a deliverable dict/object signals long-form file report."""
    if deliverable is None:
        return False
    if isinstance(deliverable, dict):
        min_length = int(deliverable.get("min_length") or 0)
        name = str(deliverable.get("name") or "")
        requires_files = bool(deliverable.get("requires_files"))
        form = deliverable.get("form")
    else:
        min_length = int(getattr(deliverable, "min_length", 0) or 0)
        name = str(getattr(deliverable, "name", "") or "")
        requires_files = bool(getattr(deliverable, "requires_files", False))
        form = getattr(deliverable, "form", None)
    if min_length >= 3_000:
        return True
    if has_word_count_commitment(name):
        return True
    if requires_files and has_word_count_commitment(name):
        return True
    return bool(form == "files" and has_word_count_commitment(name))


def plan_signals_long_form_audit(plan_nodes: object) -> bool:
    """True when any plan node task/deliverable looks like committed long-form."""
    if not isinstance(plan_nodes, (list, tuple)):
        return False
    for node in plan_nodes:
        task = getattr(node, "task", None) or (
            node.get("task") if isinstance(node, dict) else None
        )
        role = getattr(node, "role", None) or (
            node.get("role") if isinstance(node, dict) else None
        )
        deliverable = getattr(node, "deliverable", None)
        if deliverable is None and isinstance(node, dict):
            deliverable = node.get("deliverable")
        blob = " ".join(
            str(x) for x in (task, role) if isinstance(x, str) and x.strip()
        )
        if is_research_report_intent(blob) or has_word_count_commitment(blob):
            return True
        if deliverable_signals_long_form(deliverable):
            return True
    return False


def research_report_main_artifact(output_path: str | None = None) -> str:
    """Single main-file path for research_report acceptance (merge gate)."""
    cleaned = (output_path or "").strip().replace("\\", "/")
    if cleaned:
        return cleaned.lstrip("/")
    return DEFAULT_RESEARCH_REPORT_ARTIFACT
