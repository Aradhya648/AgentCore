"""Delegate playbook declaration gate (建站 / 绿场软件硬锁；其余自由组队).

自由组队：可不传 playbook，直接手写 ``tasks``（``playbook_none_reason`` 可选）。
建站 / 工具台意图：硬拒 ``none`` 与缺省手写旁路，必须 ``build_website`` /
``build_toolshed``。绿场软件 / SPA 完整交付：硬拒 ``none`` / 手写，必须 ``build_app``。
软件薄 HTML 旁路保留窄硬拒（不伴随「优先 build_feature」）。

Agent/自动化开工形态（定案甲）：记账为可运行自动化 / 仅方案时禁止 ``build_toolshed``；
仅方案另禁 ``build_website``；可运行/仅方案豁免建站 none 硬锁（自由组队）。

Regression:
``trace_id=7b39eb17c4314f1cbf76a3c84d2c365e`` (consult_skill miss → none + 两节点);
``trace_id=0483b9ecd2734d3daafd142b05cafd98`` (思维导图软件 → none + 单 HTML).
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
from agentcore.runtime.runs.software_app import (
    is_software_app_intent,
    is_software_greenfield_none_rejected,
    software_greenfield_none_path_blocked,
    software_greenfield_none_rejected_message,
    software_none_path_blocked,
    software_thin_html_rejected_message,
)
from agentcore.runtime.runs.website_style import (
    is_site_build_intent,
    is_website_continuation_intent,
    is_website_followup_exempt,
    is_website_shaped_call,
)

_PLAYBOOK_NONE = "none"

DeclarationRejectGate = Literal[
    "website", "software", "software_greenfield", "empty", "unknown", "automation"
]

_EMPTY_DELEGATE_MSG = (
    "delegate 须传手写 `tasks`，或具名 `playbook`/`playbook_id` + `playbook_args`。"
    f"建站 / 落地页 / 营销官网【必须】用 `playbook=\"build_website\"`；"
    f"控制台 / 后台 / 工具台 dense【必须】用 `playbook=\"build_toolshed\"`；"
    f"绿场软件 / SPA 完整交付【必须】用 `playbook=\"build_app\"`"
    f"（可用：{available_playbooks()}）。"
    "其余任务自由组队：按任务手写 tasks 即可，形状词仅供对照（可选快捷展开）。"
)

_WEBSITE_NONE_REJECTED_PREFIX = (
    "建站 / 落地页 / 营销官网 / 控制台 / 工具台意图下禁止 `playbook_id=\"none\"`"
)

_WEBSITE_NONE_REJECTED_MSG = (
    f"{_WEBSITE_NONE_REJECTED_PREFIX}"
    "（或缺省手写 tasks 旁路）。"
    "营销落地页必须使用 `playbook=\"build_website\"`；"
    "控制台 / 后台 / 工具台 dense 必须使用 `playbook=\"build_toolshed\"`"
    f"+ `playbook_args`。可用：{available_playbooks()}。"
    "任务书只传事实输入；禁止手糊「内容→前端」两节点绕过 P1 质量管线。"
    "非建站 / 非控制台任务勿走此路径——手写 tasks 即可。"
    "可先 `consult_skill(\"build_website\")` 或 `consult_skill(\"build_toolshed\")` 拉回用法。"
)


def website_none_rejected_message() -> str:
    """Stable reject copy for site / toolshed ``none`` bypass (probe / tests)."""
    return _WEBSITE_NONE_REJECTED_MSG


def is_website_none_rejected(error: str | None) -> bool:
    """True when ``error`` is the website / toolshed none-path reject message."""
    if not error:
        return False
    return error.startswith(_WEBSITE_NONE_REJECTED_PREFIX) or error == _WEBSITE_NONE_REJECTED_MSG


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
    if is_website_none_rejected(error):
        return "website"
    if is_software_greenfield_none_rejected(error):
        return "software_greenfield"
    soft = software_thin_html_rejected_message()
    if error == soft or error.startswith(soft[:24]):
        return "software"
    if error == _EMPTY_DELEGATE_MSG or error.startswith("delegate 须传手写"):
        return "empty"
    return "unknown"


def _call_intent_blob(arguments: dict[str, Any]) -> str:
    """Text owned by this delegate call (tasks / none_reason / playbook_args)."""
    parts: list[str] = []
    reason = arguments.get("playbook_none_reason")
    if isinstance(reason, str) and reason.strip():
        parts.append(reason)
    args = arguments.get("playbook_args")
    if isinstance(args, dict):
        for value in args.values():
            if isinstance(value, str) and value.strip():
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(item) for item in value if item)
    tasks = arguments.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for key in ("role", "task"):
                val = task.get(key)
                if isinstance(val, str) and val.strip():
                    parts.append(val)
    return " ".join(parts)


def _automation_skips_website_hard_lock(
    automation_delivery: DeliveryConfirmation | None,
) -> bool:
    """可运行自动化 / 仅方案 → 不强制进 website/toolshed 硬锁流水线。"""
    return is_runnable_delivery(automation_delivery) or is_plan_only_delivery(
        automation_delivery
    )


def website_none_path_blocked(
    arguments: dict[str, Any],
    *,
    user_message: str = "",
    automation_delivery: DeliveryConfirmation | None = None,
) -> bool:
    """True when the ``none`` / hand-written path must be rejected for site build.

    **Intent sources** (OR): user turn text + this call's tasks / ``playbook_none_reason``
    / ``playbook_args`` — construction-oriented regex
    （``is_site_build_intent`` = marketing OR toolshed）.

    **Continuation gate**: user「继续完成官网 / 补全分区…」+ call blob 呈建站形
    （官网 / ``build_website`` / ``index.html``…）→ also block ``none``（禁手糊整站续作）。
    Continuation phrases alone（「继续完成项目的开发」）do **not** trip without a
    site / toolshed anchor.

    **Software priority**: when ``is_software_app_intent`` and not site build,
    do **not** block here — ``software_none_path_blocked`` /
    ``software_greenfield_none_path_blocked`` own software rejects.

    **Automation delivery**: 可运行自动化 / 仅方案 → never force website/toolshed hard-lock
    (free teaming / build_feature). 控制台原型 keeps existing toolshed forcing.

    **Mis-injury strategy**: mid-turn audit / fix after a site exists is exempt when
    the *call payload* is follow-up-framed (审计/修复/…) **and** does not itself
    restate greenfield construction. Bare「官网」in an audit task alone does not
    trip the gate. Pure「继续」+ 改配置（call 无建站形）不拦。Vague ``none`` under
    a clear「做官网」/「做控制台」user turn still rejects (closes the hand-write bypass).
    """
    if _automation_skips_website_hard_lock(automation_delivery):
        return False
    call_blob = _call_intent_blob(arguments)
    user = user_message or ""
    if is_website_followup_exempt(call_blob) and not is_site_build_intent(call_blob):
        return False
    # Software / app framing wins over the website continuation gate; true site
    # greenfield still hard-blocks below (is_software_app_intent already False then).
    if is_software_app_intent(user, call_blob) and not is_site_build_intent(user, call_blob):
        return False
    if is_site_build_intent(user, call_blob):
        return True
    return bool(
        is_website_continuation_intent(user)
        and is_website_shaped_call(call_blob)
    )


def resolve_playbook_declaration(
    arguments: dict[str, Any],
    *,
    user_message: str = "",
    automation_delivery: DeliveryConfirmation | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve declaration → ``(playbook_name|None, none_reason|None, error|None)``.

    ``playbook_name`` set ⇒ expand that playbook. ``none_reason`` may be set on the
    hand-written path (optional). ``error`` set ⇒ reject the call.

    Free teaming may omit playbook entirely and pass ``tasks`` only. Site / toolshed
    / software-greenfield build intent still hard-rejects the hand-written bypass —
    except when automation delivery is 可运行自动化 / 仅方案 (website lock only).
    """
    legacy = arguments.get("playbook")
    playbook_id = arguments.get("playbook_id")
    none_reason_raw = arguments.get("playbook_none_reason")
    none_reason = (
        none_reason_raw.strip()
        if isinstance(none_reason_raw, str) and none_reason_raw.strip()
        else ""
    )

    # Prefer explicit playbook / playbook_id naming a registry entry.
    named: str | None = None
    if isinstance(legacy, str) and legacy.strip():
        named = legacy.strip()
    elif isinstance(playbook_id, str) and playbook_id.strip():
        pid = playbook_id.strip()
        if pid.casefold() != _PLAYBOOK_NONE:
            named = pid

    if named is not None:
        if named not in PLAYBOOKS:
            return None, None, (
                f"未知 playbook『{named}』；可用：{available_playbooks()}。"
                "或手写 `tasks`（可不声明 playbook）；"
                "建站须具名 `build_website` / `build_toolshed`；"
                "绿场软件须具名 `build_app`。"
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

    explicit_none = (
        isinstance(playbook_id, str)
        and playbook_id.strip().casefold() == _PLAYBOOK_NONE
    )
    tasks = arguments.get("tasks")
    has_tasks = isinstance(tasks, list) and bool(tasks)

    # Hand-written path: explicit none and/or tasks (none_reason optional).
    if explicit_none or has_tasks:
        if website_none_path_blocked(
            arguments,
            user_message=user_message,
            automation_delivery=automation_delivery,
        ):
            return None, None, _WEBSITE_NONE_REJECTED_MSG
        if software_greenfield_none_path_blocked(arguments, user_message=user_message):
            return None, None, software_greenfield_none_rejected_message()
        if software_none_path_blocked(arguments, user_message=user_message):
            return None, None, software_thin_html_rejected_message()
        return None, (none_reason or None), None

    return None, None, _EMPTY_DELEGATE_MSG
