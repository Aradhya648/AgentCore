"""Shared project-verify CLI detection for ``code_execute`` → ``test_run`` routing.

Models often stuff ``npm install`` / ``tsc`` / ``npm test`` into ``code_execute``,
which hard-caps at 60s. Same shape as :mod:`long_running` (dev servers → terminal):
hard refuse with ``contract_failure``, tip the bounded verify tool. Keep the list
the single source of truth. Patterns are command-shaped so imports like
``from 'vitest'`` / ``from 'vite'`` do not false-positive.
"""

from __future__ import annotations

import re

_PROJECT_VERIFY_COMMAND_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:npm|pnpm|yarn|bun)\s+(?:ci|install)\b",
        r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|build|typecheck|lint|ci)\b",
        r"\b(?:npx|bunx)\s+tsc\b",
        r"\b(?:pnpm|yarn)\s+exec\s+tsc\b",
        r"\btsc\s+--",
        r"\b(?:npx|bunx)\s+(?:vitest|jest)\b",
        r"\b(?:pnpm|yarn)\s+exec\s+(?:vitest|jest)\b",
        r"\bpytest(?:\s|$)",
        r"\b(?:python3?|py)\s+-m\s+pytest\b",
    )
)


def project_verify_command_match(code: str) -> str | None:
    """Return the matched project-verify snippet, or ``None`` if code looks short."""
    for pattern in _PROJECT_VERIFY_COMMAND_RES:
        found = pattern.search(code)
        if found is not None:
            return found.group(0)
    return None


def project_verify_redirect_message(matched: str) -> str:
    """``code_execute`` refusal: tip ``test_run`` without running the command."""
    return (
        f"禁止用 code_execute 跑项目级慢验证（检测到：{matched}）。"
        "本工具约 60s 硬顶，不适配 install / tsc / 全量 test·build。"
        "请改用 test_run（有界项目验证，分钟级预算）："
        "check=command 并填同一命令，或 check=test|typecheck|build。"
    )
