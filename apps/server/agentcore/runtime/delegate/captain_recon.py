"""B2 · 主管探路下传：把 CEO 本回合已看过的路径/短摘要注入 worker 开局。

产品目标：派人后工人不要从零再 list 根目录 / 通读主管刚读过的文件。
只收 ``file_list`` / ``file_read`` / ``grep``；指针 + 短截断，不转发全文 transcript。
仅在根 CEO 委派（depth=0）时启用——嵌套 lead 的 transcript 不在 ``captain_transcript``。
"""

from __future__ import annotations

import json
from typing import Any

from agentcore.llm.provider.protocol import LLMMessage

_RECON_TOOLS = frozenset({"file_list", "file_read", "grep"})
_MAX_ENTRIES = 6
_PER_SNIPPET_CHARS = 360
_TOTAL_CHARS = 1800

_HEADING_HINT = (
    "主管探路已知（本回合已看过——请直接执行任务；"
    "勿再无增量地 list 根目录或通读上列文件；缺细节再定点读）"
)


def harvest_captain_recon(
    messages: list[LLMMessage] | None,
    *,
    max_entries: int = _MAX_ENTRIES,
    per_snippet_chars: int = _PER_SNIPPET_CHARS,
    total_chars: int = _TOTAL_CHARS,
) -> str:
    """Build a short recon brief from the live CEO transcript, or ``\"\"`` if none."""
    if not messages:
        return ""
    pending: dict[str, tuple[str, str]] = {}
    lines: list[str] = []
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                name = (tc.function.name or "").strip()
                if name not in _RECON_TOOLS or not tc.id:
                    continue
                label = _target_label(name, tc.function.arguments or "")
                pending[tc.id] = (name, label)
            continue
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        meta = pending.pop(msg.tool_call_id, None)
        if meta is None:
            continue
        name, label = meta
        body = (msg.content or "").strip()
        if not body:
            continue
        # Skip hard failures — no useful recon to hand down.
        if "<!--agentcore:tool_failed-->" in body or body.startswith("错误"):
            continue
        snippet = _clip(body, per_snippet_chars)
        lines.append(f"- `{name}` `{label}` →\n{snippet}")
    if not lines:
        return ""
    # Keep the most recent peeks (closest to the delegate call).
    if len(lines) > max_entries:
        lines = lines[-max_entries:]
    text = "\n".join(lines)
    if len(text) > total_chars:
        text = text[: total_chars - 1].rstrip() + "…"
    return text


def resolve_captain_recon_for_delegate(*, depth: int) -> str:
    """Read live CEO transcript when this is a root delegate; else empty."""
    if int(depth or 0) > 0:
        return ""
    try:
        from agentcore.runtime.suspension import captain_transcript

        return harvest_captain_recon(captain_transcript.get())
    except Exception:  # noqa: BLE001 — recon is best-effort
        return ""


def _target_label(tool_name: str, raw_args: str) -> str:
    try:
        args: Any = json.loads(raw_args) if raw_args else {}
    except (TypeError, ValueError):
        args = {}
    if not isinstance(args, dict):
        return "?"
    if tool_name == "file_read":
        path = str(args.get("path") or "").strip()
        return path or "?"
    if tool_name == "file_list":
        directory = str(args.get("directory") or ".").strip() or "."
        pattern = str(args.get("pattern") or "*").strip() or "*"
        return f"{directory} ({pattern})"
    # grep
    path = str(args.get("path") or args.get("directory") or ".").strip() or "."
    pattern = str(args.get("pattern") or args.get("query") or "").strip()
    return f"{path} ~ {pattern}" if pattern else path


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def captain_recon_heading() -> str:
    """Opening-block heading (stable for tests / UI)."""
    return _HEADING_HINT
