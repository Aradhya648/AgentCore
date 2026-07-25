"""跑/修脚本 · 打开浏览器验证 —— 窄意图谓词 + 能力策略表（纯函数，无副作用）。

定案：环境能力 + 引擎收口决定终向；本模块只回答「是否命中意图」与「终向该是什么」。
"""

from __future__ import annotations

import re
from typing import Literal

ExecVerifyTerminal = Literal["delegate", "ask_user"]

# 跑/修脚本：保守窄匹配，勿误伤闲聊 / 概念直答 / 「这是什么意思」。
_RUN_FIX_SCRIPT_RE = re.compile(
    r"(?:"
    r"(?:帮我|请)?(?:跑|运行|执行)(?:一下|下)?"
    r".{0,64}"
    r"(?:\.py\b|脚本|测试|smoke|pytest|单元测试|npm\s+run|test_run)"
    r"|"
    r"(?:\.py\b|脚本|smoke_test|测试文件).{0,48}"
    r"(?:跑|运行|报错|修好|修一下|有问题就修)"
    r"|"
    r"(?:有问题就修|看看报什么错).{0,32}"
    r"(?:\.py\b|脚本|测试)?"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# 打开浏览器验证：须有「打开/浏览器/验证」语义，勿匹配交付指引里的「可在浏览器打开」。
_OPEN_BROWSER_VERIFY_RE = re.compile(
    r"(?:"
    r"(?:打开|用).{0,20}浏览器.{0,32}(?:验证|看|检查|测|能不能用)"
    r"|"
    r"(?:本地|本机).{0,16}(?:直接)?(?:打开|开).{0,20}浏览器"
    r"|"
    r"浏览器.{0,16}(?:帮我)?验证"
    r"|"
    r"(?:打开浏览器验证|浏览器验证一下)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# 可验产物路径：显式扩展名 / URL / 「路径是…」——缺则视为路径不清。
_CLEAR_ARTIFACT_PATH_RE = re.compile(
    r"(?:"
    r"[\w./\\-]+\.(?:html?|py|js|tsx?|jsx|vue|css|md)"
    r"|"
    r"https?://\S+"
    r"|"
    r"(?:路径|文件)\s*[是为：:=]\s*[\w./\\-]+"
    r")",
    re.IGNORECASE,
)


def is_run_fix_script_intent(*texts: str) -> bool:
    """True when user asks to run / fix a script (narrow; not concept Q&A)."""
    blob = " ".join(t for t in texts if isinstance(t, str) and t.strip())
    if not blob:
        return False
    return bool(_RUN_FIX_SCRIPT_RE.search(blob))


def is_open_browser_verify_intent(*texts: str) -> bool:
    """True when user asks to open a browser and verify a page/app."""
    blob = " ".join(t for t in texts if isinstance(t, str) and t.strip())
    if not blob:
        return False
    return bool(_OPEN_BROWSER_VERIFY_RE.search(blob))


def has_clear_verifiable_artifact_path(*texts: str) -> bool:
    """True when user text names a concrete path / URL to verify."""
    blob = " ".join(t for t in texts if isinstance(t, str) and t.strip())
    if not blob:
        return False
    return bool(_CLEAR_ARTIFACT_PATH_RE.search(blob))


def resolve_exec_verify_terminal(
    *,
    run_fix: bool,
    open_verify: bool,
    code_execute: bool,
    browser: bool,
    clear_artifact_path: bool,
) -> ExecVerifyTerminal | None:
    """Map intent × capability → hard terminal. ``None`` when no relevant intent.

    Strategy table (定案):
    - open_verify + (!browser | !clear_path) → ask_user
    - open_verify + browser + clear_path → delegate
    - run_fix + code_execute → delegate
    - run_fix + !code_execute → ask_user（缺执行 / 需本机未绑）
    """
    if open_verify:
        if not browser or not clear_artifact_path:
            return "ask_user"
        return "delegate"
    if run_fix:
        return "delegate" if code_execute else "ask_user"
    return None
