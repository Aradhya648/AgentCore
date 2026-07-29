"""Delegate playbook declaration gate（结构校验 + 自动化开工卡记账约束）.

自由组队：可不传 playbook，直接手写 ``tasks``（``playbook_none_reason`` 可选）。
建站 / 工具台 / 绿场软件：推荐具名 ``build_website`` / ``build_toolshed`` /
``build_app``（软引导见 skill / schema）；``none`` / 手写不再因意图硬拒。

Agent/自动化开工形态（定案甲）：记账为可运行自动化 / 仅方案时禁止 ``build_toolshed``；
仅方案另禁 ``build_website``。
"""

from __future__ import annotations

from typing import Any, Literal

from agentcore.runtime.runs.automation_delivery import (
    DeliveryConfirmation,
    automation_toolshed_rejected_message,
    automation_website_rejected_message,
    is_plan_only_delivery,
    is_runnable_delivery,
)
from agentcore.runtime.runs.playbooks import PLAYBOOKS, available_playbooks

_PLAYBOOK_NONE = "none"

DeclarationRejectGate = Literal[
    "empty",
    "unknown",
    "automation",
    "xor",
]

PLAYBOOK_TASKS_XOR_MSG = (
    "playbook 与 tasks 二选一，不可同时传。"
    "手写 tasks：去掉具名 playbook/playbook_id，只传 tasks；"
    "用可选形状：只传 playbook（+playbook_args 槽位），不要传 tasks。"
)

PLAYBOOK_ID_CONFLICT_MSG = (
    "playbook 与 playbook_id 指向不同形状，不可同传冲突值；"
    "只保留一个具名字段（或手写 tasks 时去掉两者）。"
)

HANDWRITTEN_PLAYBOOK_ARGS_MSG = (
    "手写 tasks 时勿传 playbook_args；"
    "playbook_args 仅配合具名 playbook/playbook_id 使用。"
)

_EMPTY_DELEGATE_MSG = (
    "delegate 须传手写 `tasks`，或具名 `playbook`/`playbook_id` + `playbook_args`。"
    f"建站 / 落地页 / 营销官网【推荐】用 `playbook=\"build_website\"`；"
    f"控制台 / 后台 / 工具台 dense【推荐】用 `playbook=\"build_toolshed\"`；"
    f"绿场软件 / SPA 完整交付【推荐】用 `playbook=\"build_app\"`"
    f"（可用：{available_playbooks()}）。"
    "其余任务自由组队：按任务手写 tasks 即可，形状词仅供对照（可选快捷展开）。"
)


def is_automation_playbook_rejected(error: str | None) -> bool:
    """True when ``error`` is the automation delivery playbook ban."""
    if not error:
        return False
    return error in (
        automation_toolshed_rejected_message(),
        automation_website_rejected_message(),
    ) or error.startswith("当前记账交付形态")


def declaration_reject_gate(error: str | None) -> DeclarationRejectGate:
    """Classify a declaration reject for logging / probes."""
    if not error:
        return "unknown"
    if is_automation_playbook_rejected(error):
        return "automation"
    if error in (
        PLAYBOOK_TASKS_XOR_MSG,
        PLAYBOOK_ID_CONFLICT_MSG,
        HANDWRITTEN_PLAYBOOK_ARGS_MSG,
    ) or error.startswith("playbook 与 tasks 二选一"):
        return "xor"
    if error == _EMPTY_DELEGATE_MSG or error.startswith("delegate 须传手写"):
        return "empty"
    return "unknown"


def resolve_playbook_declaration(
    arguments: dict[str, Any],
    *,
    user_message: str = "",
    automation_delivery: DeliveryConfirmation | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve declaration → ``(playbook_name|None, none_reason|None, error|None)``.

    ``playbook_name`` set ⇒ expand that playbook. ``none_reason`` may be set on the
    hand-written path (optional). ``error`` set ⇒ reject the call.

    Free teaming may omit playbook entirely and pass ``tasks`` only. Named playbooks
    still expand when declared. Automation delivery bans toolshed/website as before.
    ``user_message`` retained for call-site compatibility (no intent hard-lock).
    """
    _ = user_message  # call-site compat; soft guidance only (no intent hard-lock)
    legacy = arguments.get("playbook")
    playbook_id = arguments.get("playbook_id")
    none_reason_raw = arguments.get("playbook_none_reason")
    none_reason = (
        none_reason_raw.strip()
        if isinstance(none_reason_raw, str) and none_reason_raw.strip()
        else ""
    )

    # Prefer explicit playbook / playbook_id naming a registry entry.
    legacy_s = legacy.strip() if isinstance(legacy, str) and legacy.strip() else ""
    pid_s = (
        playbook_id.strip()
        if isinstance(playbook_id, str) and playbook_id.strip()
        else ""
    )
    if (
        legacy_s
        and pid_s
        and pid_s.casefold() != _PLAYBOOK_NONE
        and legacy_s != pid_s
    ):
        return None, None, PLAYBOOK_ID_CONFLICT_MSG

    named: str | None = None
    if legacy_s:
        named = legacy_s
    elif pid_s and pid_s.casefold() != _PLAYBOOK_NONE:
        named = pid_s

    tasks = arguments.get("tasks")
    has_tasks = isinstance(tasks, list) and bool(tasks)

    if named is not None:
        if has_tasks:
            # playbook XOR tasks — reject before expand / fanout (避免半跑).
            return None, None, PLAYBOOK_TASKS_XOR_MSG
        if named not in PLAYBOOKS:
            return None, None, (
                f"未知 playbook『{named}』；可用：{available_playbooks()}。"
                "或手写 `tasks`（可不声明 playbook）；"
                "建站推荐具名 `build_website` / `build_toolshed`；"
                "绿场软件推荐具名 `build_app`。"
            )
        # Agent/自动化记账闸：可运行/仅方案禁 toolshed；仅方案另禁 website。
        if named == "build_toolshed" and automation_delivery is not None and (
            is_runnable_delivery(automation_delivery)
            or is_plan_only_delivery(automation_delivery)
        ):
            return None, None, automation_toolshed_rejected_message()
        if named == "build_website" and is_plan_only_delivery(automation_delivery):
            return None, None, automation_website_rejected_message()
        # 具名 build_app / build_website / build_toolshed 等直接放行。
        return named, None, None

    explicit_none = pid_s.casefold() == _PLAYBOOK_NONE

    # Hand-written path: explicit none and/or tasks (none_reason optional).
    if explicit_none or has_tasks:
        if arguments.get("playbook_args"):
            return None, None, HANDWRITTEN_PLAYBOOK_ARGS_MSG
        return None, (none_reason or None), None

    return None, None, _EMPTY_DELEGATE_MSG
