"""Collapse large write-tool arguments in the model-facing window (handoff 缓存崩塌).

After a worker ``file_write`` / ``file_append`` / ``str_replace`` lands, the assistant
message still carries the FULL body inside ``tool_calls[].function.arguments``. Later
rounds re-pay that body as cache_miss (case: handoff round ~28k in / ~27k miss).

This projection — applied at request-assembly time only, like ``tool_clear`` — replaces
the write body's argument field with a stable stub once a tool result acknowledges the
call. Canonical ``messages`` / journal keep the full args; resume rebuilds then re-applies.

The stub keeps a compact **structural digest** (HTML class/id lists, CSS selectors, …)
so a multi-file worker can still contract against what it already wrote without re-paying
the full body — and without blind-writing the next file from memory alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction

WRITE_ARG_TOOLS = frozenset({"file_write", "file_append", "str_replace"})

# Argument keys that hold the bulky body for each write tool.
_BODY_KEYS = ("content", "new_str", "new_string", "replacement")

# Cap digest size (~几百 token): keep contract signal, not a second full body.
_STRUCTURE_MAX_CHARS = 1200
_STRUCTURE_MAX_ITEMS = 80

_HTML_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_HTML_CLASS_RE = re.compile(r"""\bclass\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_CSS_SELECTOR_RE = re.compile(
    r"(?m)^\s*([.#]?[A-Za-z_][\w-]*(?:\s*[.#][A-Za-z_][\w-]*)*)\s*\{"
)
_MD_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
_JS_EXPORT_RE = re.compile(
    r"(?m)^\s*(?:export\s+(?:default\s+)?(?:async\s+)?)?"
    r"(?:function\*?|class|const|let|var)\s+([A-Za-z_$][\w$]*)"
)


def _dedupe_preserve(items: list[str], *, limit: int = _STRUCTURE_MAX_ITEMS) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _clip(text: str, *, max_chars: int = _STRUCTURE_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _sniff_kind(path: str, content: str) -> str:
    ext = Path(path or "").suffix.lower()
    head = content.lstrip()[:200].lower()
    if ext in {".html", ".htm", ".xhtml"} or head.startswith(
        ("<!doctype html", "<html")
    ):
        return "html"
    if ext == ".css" or (ext == "" and "{" in content and re.search(r"[.#][\w-]+\s*\{", content)):
        return "css"
    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        return "js"
    if ext in {".md", ".markdown"}:
        return "md"
    if ext == ".json" or head[:1] in {"{", "["}:
        return "json"
    if "<" in content and ("class=" in head or "id=" in head):
        return "html"
    return "text"


def _summarize_html(content: str) -> str | None:
    ids = _dedupe_preserve(_HTML_ID_RE.findall(content))
    classes: list[str] = []
    for group in _HTML_CLASS_RE.findall(content):
        classes.extend(group.split())
    classes = _dedupe_preserve(classes)
    if not ids and not classes:
        return None
    parts: list[str] = ["HTML 结构摘要"]
    if ids:
        parts.append("ids=[" + ", ".join(ids) + "]")
    if classes:
        parts.append("classes=[" + ", ".join(classes) + "]")
    return _clip("; ".join(parts))


def _summarize_css(content: str) -> str | None:
    selectors = _dedupe_preserve(_CSS_SELECTOR_RE.findall(content))
    if not selectors:
        return None
    return _clip("CSS 选择器摘要: [" + ", ".join(selectors) + "]")


def _summarize_md(content: str) -> str | None:
    headings: list[str] = []
    for marks, title in _MD_HEADING_RE.findall(content):
        headings.append(f"{marks} {title.strip()}")
    headings = _dedupe_preserve(headings)
    if not headings:
        return None
    return _clip("Markdown 标题摘要: [" + ", ".join(headings) + "]")


def _summarize_js(content: str) -> str | None:
    names = _dedupe_preserve(_JS_EXPORT_RE.findall(content))
    if not names:
        return None
    return _clip("JS/TS 符号摘要: [" + ", ".join(names) + "]")


def _summarize_json(content: str) -> str | None:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if isinstance(data, dict):
        keys = _dedupe_preserve([str(k) for k in data])
        if not keys:
            return None
        return _clip("JSON 顶层键: [" + ", ".join(keys) + "]")
    if isinstance(data, list):
        return _clip(f"JSON 数组摘要: len={len(data)}")
    return None


def structural_write_summary(path: str, content: str) -> str | None:
    """Compact structural digest of a write body (class/id / selectors / headings…).

    Returns None when no useful structure is found. Size-capped for context budget.
    """
    if not isinstance(content, str) or not content.strip():
        return None
    kind = _sniff_kind(path, content)
    if kind == "html":
        return _summarize_html(content)
    if kind == "css":
        return _summarize_css(content)
    if kind == "md":
        return _summarize_md(content)
    if kind == "js":
        return _summarize_js(content)
    if kind == "json":
        return _summarize_json(content)
    return None


def _body_text(data: dict) -> str:
    for key in _BODY_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def write_args_stub(tool_name: str, arguments: str, original_len: int) -> str:
    """Stable stub arguments: keep path/pattern identity + structural digest, drop body."""
    path = ""
    pattern = ""
    try:
        data = json.loads(arguments) if arguments else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        data = {}
    body = ""
    if isinstance(data, dict):
        path = str(data.get("path") or data.get("file_path") or "")
        pattern = str(data.get("old_str") or data.get("pattern") or "")[:80]
        body = _body_text(data)
    stub: dict[str, str] = {
        "_cleared": (
            f"{tool_name} 正文已从上下文窗口移除（原 {original_len} 字符）；"
            "内容已落盘，如需细节请 file_read。"
        )
    }
    if path:
        stub["path"] = path
    summary = structural_write_summary(path, body)
    if summary:
        stub["_structure"] = summary
    if pattern and tool_name == "str_replace":
        stub["old_str"] = pattern
        stub["new_str"] = "[已清理]"
    elif tool_name in {"file_write", "file_append"}:
        stub["content"] = "[已清理]"
    return json.dumps(stub, ensure_ascii=False)


def _body_len(arguments: str) -> int:
    try:
        data = json.loads(arguments) if arguments else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return len(arguments or "")
    if not isinstance(data, dict):
        return len(arguments or "")
    total = 0
    for key in _BODY_KEYS:
        val = data.get(key)
        if isinstance(val, str):
            total += len(val)
    return total or len(arguments or "")


def project_cleared_write_args(
    messages: list[LLMMessage],
    *,
    min_chars: int = 500,
) -> list[LLMMessage]:
    """Collapse bulky write-tool args once their tool result is present.

    Returns the same list when nothing qualifies. Prefix-cache safe for a given
    completed write: stub is a pure function of (tool, path, body structure, original_len).
    """
    if min_chars < 0:
        return messages

    # tool_call_id → (tool_name, arguments, assistant_msg_index, call_index)
    call_meta: dict[str, tuple[str, str, int, int]] = {}
    for mi, message in enumerate(messages):
        if message.role != "assistant" or not message.tool_calls:
            continue
        for ci, call in enumerate(message.tool_calls):
            name = call.function.name
            if name not in WRITE_ARG_TOOLS:
                continue
            args = call.function.arguments or ""
            if _body_len(args) < min_chars:
                continue
            # Already cleared stubs are small / marked.
            if '"_cleared"' in args:
                continue
            call_meta[call.id] = (name, args, mi, ci)

    if not call_meta:
        return messages

    # Only collapse writes that already have a tool result (completed round).
    completed_ids = {
        m.tool_call_id
        for m in messages
        if m.role == "tool" and m.tool_call_id and m.tool_call_id in call_meta
    }
    if not completed_ids:
        return messages

    # Rebuild only assistant messages that need a call rewritten.
    touch_indices = {call_meta[cid][2] for cid in completed_ids}
    projected: list[LLMMessage] = []
    for mi, message in enumerate(messages):
        if mi not in touch_indices or not message.tool_calls:
            projected.append(message)
            continue
        new_calls: list[ToolCall] = []
        changed = False
        for call in message.tool_calls:
            if call.id in completed_ids:
                name, args, _, _ = call_meta[call.id]
                stub = write_args_stub(name, args, _body_len(args))
                new_calls.append(
                    ToolCall(
                        id=call.id,
                        function=ToolCallFunction(name=name, arguments=stub),
                    )
                )
                changed = True
            else:
                new_calls.append(call)
        if changed:
            projected.append(
                LLMMessage(
                    role="assistant",
                    content=message.content,
                    tool_calls=new_calls,
                    reasoning_content=message.reasoning_content,
                )
            )
        else:
            projected.append(message)
    return projected
