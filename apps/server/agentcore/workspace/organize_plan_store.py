"""Session-scoped organize-plan grants (方案确认 → 批次授权).

When the user confirms an ``organize_plan`` ask_user card, the kept items are
registered here. A subsequent ``file_batch`` that carries ``organize_plan_id``
and only in-plan operations skips the GRANTABLE approval gate (single confirm,
no second card). Scope is conversation + session only — not durable.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

_lock = threading.Lock()
_plans: dict[str, OrganizePlan] = {}


@dataclass
class OrganizePlan:
    plan_id: str
    conversation_id: str
    """Canonical ops the user kept (subset of the card options)."""
    operations: list[dict[str, Any]] = field(default_factory=list)
    """False after undo or explicit consume — further batches with this id fail."""
    active: bool = True


def _op_key(item: dict[str, Any]) -> tuple[str, ...]:
    op = str(item.get("op", "")).strip()
    if op in ("move", "copy"):
        return (
            op,
            str(item.get("source", "")).strip(),
            str(item.get("destination", "")).strip(),
        )
    if op in ("delete", "mkdir"):
        return (op, str(item.get("path", "")).strip(), "")
    return (op, "", "")


def register_plan(
    *,
    plan_id: str,
    conversation_id: str,
    operations: list[dict[str, Any]],
) -> OrganizePlan:
    plan = OrganizePlan(
        plan_id=plan_id,
        conversation_id=conversation_id,
        operations=list(operations),
        active=True,
    )
    with _lock:
        _plans[plan_id] = plan
    return plan


def get_plan(plan_id: str) -> OrganizePlan | None:
    with _lock:
        return _plans.get(plan_id)


def deactivate_plan(plan_id: str) -> bool:
    with _lock:
        plan = _plans.get(plan_id)
        if plan is None:
            return False
        plan.active = False
        return True


def clear_conversation(conversation_id: str) -> None:
    with _lock:
        dead = [pid for pid, p in _plans.items() if p.conversation_id == conversation_id]
        for pid in dead:
            del _plans[pid]


def ops_within_plan(plan: OrganizePlan, operations: list[dict[str, Any]]) -> str | None:
    """Return an error if any op is outside the plan; else None."""
    if not plan.active:
        return f"整理方案 {plan.plan_id} 已失效（已撤销或已消耗）"
    allowed = {_op_key(op) for op in plan.operations}
    for item in operations:
        if not isinstance(item, dict):
            return "operations 条目必须是对象"
        key = _op_key(item)
        if key not in allowed:
            return f"操作不在已确认方案内：{key[0]} {key[1]}→{key[2]}".rstrip("→")
        if bool(item.get("permanent")):
            return "整理方案禁止 permanent=true 删除"
    return None


def plan_covers_batch(
    *,
    plan_id: str,
    conversation_id: str,
    operations: list[Any],
) -> bool:
    """True when ``file_batch`` may skip the approval gate under this plan."""
    plan = get_plan(plan_id)
    if plan is None or not plan.active:
        return False
    if plan.conversation_id != conversation_id:
        return False
    if not isinstance(operations, list) or not operations:
        return False
    typed = [op for op in operations if isinstance(op, dict)]
    if len(typed) != len(operations):
        return False
    return ops_within_plan(plan, typed) is None


def clear_all_for_tests() -> None:
    with _lock:
        _plans.clear()
