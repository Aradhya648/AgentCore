"""Official playbook → user-workflow copy catalog (read-only templates).

User workflows are **not** registered into ``PLAYBOOKS``. 「使用」= expand once and
persist a definition snapshot under ``user_workflows``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from agentcore.runtime.runs.playbooks import PLAYBOOKS, expand_playbook
from agentcore.workflows.definition import (
    WorkflowDefinitionError,
    tasks_dropped_meta_keys,
    tasks_to_workflow_definition,
)

# Desktop template UI only has string textareas; builders expect list for angles.
_LIST_SLOT_SPLIT = re.compile(r"[,，、\n]+")


def _coerce_list_slot(val: Any) -> Any:
    """Accept JSON array text or comma/顿号/newline-separated strings → list."""
    if isinstance(val, list) or not isinstance(val, str):
        return val
    s = val.strip()
    if not s:
        return val
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    parts = [p.strip() for p in _LIST_SLOT_SPLIT.split(s) if p.strip()]
    return parts if parts else val

# First-period official list (product). Other PLAYBOOKS names → explicit reject.
WORKFLOW_PLAYBOOK_IDS: tuple[str, ...] = (
    "research_report",
    "multi_lens_research",
    "parallel_brief",
    "build_feature",
    "build_app",
    "build_website",
    "build_toolshed",
)

_KNOWN: frozenset[str] = frozenset(WORKFLOW_PLAYBOOK_IDS)

# Required primary slots the API asks the user to fill (builders may accept more).
PRIMARY_SLOTS: dict[str, tuple[str, ...]] = {
    "research_report": ("topic",),
    "multi_lens_research": ("topic",),
    "parallel_brief": ("topic", "angles"),
    "build_feature": ("feature",),
    "build_app": ("app",),
    "build_website": ("site",),
    "build_toolshed": ("site",),
}

# Soft optional defaults merged under user slots (user wins). Builders already default
# many optionals when omitted; these only make the snapshot more explicit / stable.
_DEFAULT_OPTIONAL_SLOTS: dict[str, dict[str, Any]] = {
    "research_report": {"checkpoint": True},
}

_TITLE: dict[str, str] = {
    "research_report": "调研报告成文",
    "multi_lens_research": "多透镜调研",
    "parallel_brief": "多角对齐摸底",
    "build_feature": "功能交付",
    "build_app": "绿场应用搭建",
    "build_website": "营销站点搭建",
    "build_toolshed": "工具台搭建",
}

_PRIMARY_SLOT_HELP: dict[str, str] = {
    "research_report": "topic（必填，主题）",
    "multi_lens_research": "topic（必填，主题/事件）",
    "parallel_brief": (
        "topic（必填，主题）；angles（必填，≥2 个可并行方向；"
        "数组或逗号/顿号分隔文本）"
    ),
    "build_feature": "feature（必填，要实现的功能）",
    "build_app": "app（必填，应用/SPA 简述）",
    "build_website": "site（必填，站点/落地页简述）",
    "build_toolshed": "site（必填，控制台/工具台简述）",
}

_DEGRADE_NOTE = (
    "复制为我的工作流时不保留 tools / max_rounds / timeout_ms 等执行细项，可在画布自行调整。"
)


@dataclass(frozen=True, slots=True)
class PlaybookTemplateItem:
    id: str
    title: str
    summary: str
    primary_slots: str


class PlaybookTemplateError(ValueError):
    """Unknown / not-in-catalog playbook, missing primary slot, or expand failure."""


def is_workflow_playbook(name: str | None) -> bool:
    return bool(name) and name in _KNOWN


def list_playbook_templates() -> list[PlaybookTemplateItem]:
    out: list[PlaybookTemplateItem] = []
    for pid in WORKFLOW_PLAYBOOK_IDS:
        pb = PLAYBOOKS.get(pid)
        base_summary = pb.summary if pb is not None else ""
        summary = f"{base_summary}（{_DEGRADE_NOTE}）" if base_summary else _DEGRADE_NOTE
        out.append(
            PlaybookTemplateItem(
                id=pid,
                title=_TITLE.get(pid, pid),
                summary=summary,
                primary_slots=_PRIMARY_SLOT_HELP.get(pid, pb.slots if pb else ""),
            )
        )
    return out


def merge_playbook_slots(playbook: str, slots: dict[str, Any] | None) -> dict[str, Any]:
    """Validate catalog membership + primary slots; merge soft optional defaults."""
    if not is_workflow_playbook(playbook):
        if playbook in PLAYBOOKS:
            raise PlaybookTemplateError(
                f"playbook「{playbook}」暂未列入官方工作流模板；"
                f"可用：{', '.join(WORKFLOW_PLAYBOOK_IDS)}"
            )
        raise PlaybookTemplateError(
            f"未知 playbook「{playbook}」；可用：{', '.join(WORKFLOW_PLAYBOOK_IDS)}"
        )
    if slots is not None and not isinstance(slots, dict):
        raise PlaybookTemplateError("slots 必须是对象")

    merged: dict[str, Any] = dict(_DEFAULT_OPTIONAL_SLOTS.get(playbook) or {})
    merged.update(dict(slots or {}))

    # parallel_brief.angles: coerce UI string → list before missing/expand checks.
    if playbook == "parallel_brief" and "angles" in merged:
        merged["angles"] = _coerce_list_slot(merged["angles"])

    missing: list[str] = []
    for key in PRIMARY_SLOTS[playbook]:
        val = merged.get(key)
        if isinstance(val, str):
            if not val.strip():
                missing.append(key)
        elif val is None or isinstance(val, list) and len(val) == 0:
            missing.append(key)
        # Non-empty list / other types → leave to expand_playbook errors.
    if missing:
        help_text = _PRIMARY_SLOT_HELP[playbook]
        raise PlaybookTemplateError(f"缺少主槽：{', '.join(missing)}；需要 {help_text}")
    return merged


def instantiate_from_playbook(
    playbook: str,
    slots: dict[str, Any] | None,
    *,
    name: str | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    """Expand official playbook → workflow definition snapshot.

    Returns ``(name, description, definition)`` ready for ``UserWorkflowRepository.create``.
    """
    merged = merge_playbook_slots(playbook, slots)
    tasks, errors = expand_playbook(playbook, merged)
    if errors:
        raise PlaybookTemplateError("；".join(errors))
    if not tasks:
        raise PlaybookTemplateError(f"playbook「{playbook}」展开结果为空")

    try:
        definition = tasks_to_workflow_definition(tasks)
    except WorkflowDefinitionError as e:
        raise PlaybookTemplateError(str(e)) from e

    title = _TITLE.get(playbook, playbook)
    primary_key = PRIMARY_SLOTS[playbook][0]
    primary_val = merged.get(primary_key)
    primary_label = (
        primary_val.strip()
        if isinstance(primary_val, str) and primary_val.strip()
        else ""
    )
    resolved_name = (name or "").strip() or (
        f"{title} · {primary_label}" if primary_label else title
    )

    dropped = tasks_dropped_meta_keys(tasks)
    desc_parts = [f"由官方模板「{title}」（{playbook}）复制"]
    if dropped:
        desc_parts.append(f"已降级字段：{', '.join(dropped)}")
    description = "；".join(desc_parts)

    return resolved_name, description, definition
