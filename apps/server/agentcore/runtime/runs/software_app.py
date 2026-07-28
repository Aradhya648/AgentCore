"""软件 / 应用类工程意图谓词（kickoff 交付形态 + playbook 声明闸复用）.

软件意图下保留窄硬拒：禁止「单前端 + 单 HTML / 仅因单文件缩成 1 worker」旁路。
绿场软件 / SPA 完整交付另有硬锁：命中则禁 ``none`` / 手写 tasks，必须 ``build_app``。
官网 / toolshed 仍走 ``website_style`` 硬闸，本模块与之正交（site 意图优先排除）。
``build_feature`` 为可选形状快捷，不文案强推「优先」。
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.runtime.runs.website_style import is_site_build_intent

# 绿场「做软件 / 应用」：构建动词靠近软件名词；不含官网 / 控制台（由 site 闸吃）。
_SOFTWARE_APP_INTENT_RE = re.compile(
    r"(?:"
    r"(?:做|建|搭建|构建|制作|开发|写|帮.?我)"
    r".{0,36}"
    r"(?:软件|应用|小程序|客户端|桌面端|桌面应用|App\b|web\s*app|desktop\s*app|"
    r"工具软件|小工具|productivity\s+tool)"
    r"|"
    r"(?:软件|应用|小程序|客户端|桌面应用|App\b|web\s*app|desktop\s*app|"
    r"工具软件|小工具)"
    r".{0,36}"
    r"(?:做|建|搭建|构建|制作|开发)"
    r"|"
    r"(?:build|create|make|develop)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:\w+[\s-]+){0,3}"
    r"(?:software|application|\bapp\b|web\s*app|desktop\s*app|tool(?:\s*app)?)"
    r"|"
    r"(?:手写|hand[- ]?writ).{0,40}"
    r"(?:软件|应用|build_feature)"
    r"|"
    r"build_feature.{0,48}(?:未|不|miss|没有|不可|目录)"
    r")",
    re.IGNORECASE,
)

# 绿场完整交付：从 0 到 1 / 完整 SPA / Vite·Vue·React 看板等（site 优先排除）。
_SOFTWARE_GREENFIELD_INTENT_RE = re.compile(
    r"(?:"
    r"从\s*0\s*到\s*1|从零(?:开始|搭建|构建|开发)|"
    r"搭建完整项目|按文档实现全部功能|"
    r"完整.{0,12}(?:应用|项目|SPA|系统)|"
    r"(?:做|建|开发|搭建|构建|制作).{0,36}"
    r"(?:Vue|React|Vite|SPA|看板|dashboard|数据看板|"
    r"前端项目|前端应用|单页应用|web\s*app)"
    r"|"
    r"(?:Vue|React|Vite|SPA|看板|dashboard|数据看板|"
    r"前端项目|前端应用|单页应用|web\s*app)"
    r".{0,36}(?:做|建|开发|搭建|构建|制作)"
    r"|"
    r"(?:build|create|scaffold|greenfield).{0,40}"
    r"(?:vue|react|vite|\bspa\b|dashboard|full[- ]?stack\s+app)"
    r"|"
    r"build_app"
    r")",
    re.IGNORECASE,
)

# none 旁路：单 HTML / 单文件 HTML 塌缩信号。
_SINGLE_HTML_RE = re.compile(
    r"(?:"
    r"单\s*HTML|单文件\s*(?:的\s*)?HTML|一个\s*HTML|纯\s*HTML|"
    r"单页\s*HTML|single[- ]?(?:file\s+)?html|one[- ]file\s*html|"
    r"browser[- ]?only.{0,12}html"
    r")",
    re.IGNORECASE,
)

# 任务正文点名单 .html 交付（无「单 HTML」字样时仍视为薄路径）。
_HTML_ARTIFACT_RE = re.compile(
    r"(?:[\w.-]+\.html|\bsite/index\.html\b)",
    re.IGNORECASE,
)

# 「仅因单文件」缩成 1 worker 的理由腔。
_SINGLE_FILE_SHRINK_RE = re.compile(
    r"(?:"
    r"单文件|一个文件|single\s*file"
    r").{0,48}"
    r"(?:即可|就够|足够|简单|轻量|能交付|就行|够用|缩成|只要)"
    r"|"
    r"(?:因为|由于|就|仅|只).{0,16}"
    r"(?:单文件|一个文件|single\s*file)",
    re.IGNORECASE,
)

_FRONTEND_ROLE_RE = re.compile(r"前端|frontend|ui\s*engineer|web\s*dev", re.IGNORECASE)

# 用户已在开工卡拍板交付形态后的显式豁免（可观测理由）。
_USER_CONFIRMED_DELIVERY_RE = re.compile(
    r"(?:"
    r"用户(?:已)?(?:确认|选定|选择|同意|拍板).{0,32}"
    r"(?:交付形态|单页原型|可运行单页|仅(?:方案)?文档|单\s*HTML|本地多文件)"
    r"|"
    r"(?:交付形态|开工卡).{0,24}(?:已确认|用户选定)"
    r")",
    re.IGNORECASE,
)

_SOFTWARE_THIN_HTML_REJECTED_MSG = (
    "做软件 / 应用意图下禁止单前端 / 单 HTML 旁路"
    "（不得仅因「单文件」缩成 1 worker）。"
    "请手写多角色工程拆分，或选用可选形状 `playbook=\"build_feature\"` + `playbook_args`；"
    "若用户已在开工卡选定「可运行单页原型 / 仅方案文档」等交付形态，"
    "须在理由或任务书中写明「用户已确认交付形态…」。"
)

_SOFTWARE_GREENFIELD_NONE_REJECTED_PREFIX = (
    "绿场软件 / SPA 完整交付意图下禁止 `playbook_id=\"none\"`"
)

_SOFTWARE_GREENFIELD_NONE_REJECTED_MSG = (
    f"{_SOFTWARE_GREENFIELD_NONE_REJECTED_PREFIX}"
    "（或缺省手写 tasks 旁路）。"
    "从 0 到 1 / 完整 Vite·Vue·React·SPA / 数据看板【必须】"
    "使用 `playbook=\"build_app\"` + `playbook_args`（app 必填；"
    "可选 modules / stack / root）。"
    "禁止手糊单 worker 包整站绕过 scaffold-first 多波管线。"
    "非绿场完整交付（局部改码 / 单功能）勿走此路径——手写 tasks 或 "
    "`build_feature` 即可。"
    "可先 `consult_skill(\"build_app\")` 拉回用法。"
)


def is_software_app_intent(*parts: str) -> bool:
    """True when text frames greenfield software / app construction.

    Orthogonal to site / toolshed：官网与控制台由 :func:`is_site_build_intent` 吃，
    本谓词对其返回 False，避免双闸打架。
    """
    blob = " ".join(p for p in parts if isinstance(p, str) and p.strip())
    if not blob:
        return False
    if is_site_build_intent(blob):
        return False
    return bool(_SOFTWARE_APP_INTENT_RE.search(blob))


def is_software_greenfield_intent(*parts: str) -> bool:
    """True for 从0到1 / 完整 SPA / Vite·Vue·React 看板等绿场完整交付.

    Site / toolshed 优先：命中 ``is_site_build_intent`` → False（互斥）。
    """
    blob = " ".join(p for p in parts if isinstance(p, str) and p.strip())
    if not blob:
        return False
    if is_site_build_intent(blob):
        return False
    return bool(_SOFTWARE_GREENFIELD_INTENT_RE.search(blob))


def _task_blob(arguments: dict[str, Any]) -> str:
    parts: list[str] = []
    reason = arguments.get("playbook_none_reason")
    if isinstance(reason, str) and reason.strip():
        parts.append(reason)
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


def _user_confirmed_delivery(blob: str) -> bool:
    return bool(blob and _USER_CONFIRMED_DELIVERY_RE.search(blob))


def is_software_thin_html_none_path(arguments: dict[str, Any]) -> bool:
    """True when hand-written path collapses to 1 frontend / single-HTML.

    Does **not** fire when ``playbook_none_reason`` explicitly cites a user-confirmed
    delivery form from the kickoff card.
    """
    tasks = arguments.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        return False
    blob = _task_blob(arguments)
    if _user_confirmed_delivery(blob):
        return False
    if _SINGLE_HTML_RE.search(blob):
        return True
    if _SINGLE_FILE_SHRINK_RE.search(blob):
        return True
    task0 = tasks[0] if isinstance(tasks[0], dict) else {}
    role = str(task0.get("role") or "")
    task_text = str(task0.get("task") or "")
    reason = str(arguments.get("playbook_none_reason") or "")
    return bool(
        _FRONTEND_ROLE_RE.search(role)
        and (
            _SINGLE_HTML_RE.search(blob)
            or _SINGLE_FILE_SHRINK_RE.search(reason)
            or _HTML_ARTIFACT_RE.search(task_text)
            or "单文件" in task_text
        )
    )


def software_none_path_blocked(
    arguments: dict[str, Any],
    *,
    user_message: str = "",
) -> bool:
    """True when software intent + thin none path must be rejected."""
    call_blob = _task_blob(arguments)
    if not is_software_app_intent(user_message or "", call_blob):
        return False
    return is_software_thin_html_none_path(arguments)


def software_greenfield_none_path_blocked(
    arguments: dict[str, Any],
    *,
    user_message: str = "",
) -> bool:
    """True when greenfield SPA intent + none / hand-written path must be rejected."""
    call_blob = _task_blob(arguments)
    return is_software_greenfield_intent(user_message or "", call_blob)


def software_thin_html_rejected_message() -> str:
    return _SOFTWARE_THIN_HTML_REJECTED_MSG


def software_greenfield_none_rejected_message() -> str:
    return _SOFTWARE_GREENFIELD_NONE_REJECTED_MSG


def is_software_greenfield_none_rejected(error: str | None) -> bool:
    if not error:
        return False
    return (
        error.startswith(_SOFTWARE_GREENFIELD_NONE_REJECTED_PREFIX)
        or error == _SOFTWARE_GREENFIELD_NONE_REJECTED_MSG
    )
