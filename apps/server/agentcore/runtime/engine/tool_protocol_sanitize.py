"""Strip vendor tool-call protocol tags leaking into tool names / args / prose.

Some OpenAI-compatible providers (e.g. LongCat) occasionally emit residual XML-like
markers such as ``</longcat_arg_key>`` or ``<longcat_tool_call>`` inside tool names,
argument strings, or handoff summary text. Clean at the tool-exec / harvest seam so
illegal names become retryable and briefs stay readable — no provider-specific adapter.

Also used **before** ``json.loads`` on raw tool-call arguments: models sometimes mix
Anthropic-style ``<parameter>`` / ``<object>`` fragments into OpenAI JSON args, which
would otherwise hard-fail as ``args_parse_failed``.

After a successful ``json.loads``, :func:`unwrap_nested_delegate_arguments` eats one
known protocol fumble: double-wrapping the payload as ``{"arguments": "<json>"}``
(wire field name collision) — same family as ``coerce_list_arg`` / hoist, not generic
JSON repair.

:func:`salvage_handoff_raw_arguments` is a second, **handoff-only** narrow pass after
sanitize when ``json.loads`` still fails: quote known bare string fields and close
truncated brackets/strings. Structural only — no generic JSON-repair black box.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = [
    "salvage_handoff_raw_arguments",
    "sanitize_protocol_text",
    "sanitize_raw_tool_arguments",
    "sanitize_tool_args",
    "sanitize_tool_name",
    "unwrap_nested_delegate_arguments",
]

# Handoff schema string leaves that models often emit without quotes.
_HANDOFF_BARE_STRING_KEYS = frozenset({"summary", "assumptions", "next_steps"})
_HANDOFF_BARE_KEY_RE = re.compile(
    r'"(summary|assumptions|next_steps)"\s*:\s*',
)

# Delegate payload carriers — used to decide whether nested ``arguments`` is the
# sole top-level payload key (narrow unwrap; do not guess other fields).
_DELEGATE_PAYLOAD_KEYS = frozenset({"tasks", "playbook", "playbook_id", "arguments"})

# Vendor / generic tool-protocol tags (open or close), optionally with attrs.
# Includes bare structural wrappers (``object`` / ``list`` / ``item``) seen when
# XML-style tool calling leaks into JSON arguments.
_PROTOCOL_TAG_RE = re.compile(
    r"</?"
    r"(?:longcat_)?"
    r"(?:arg_key|arg_value|tool_call|tool_name|parameter|arguments?|function|"
    r"object|list|item|invoke|tool)"
    r"(?:\s[^>]*)?>",
    re.IGNORECASE,
)
# Hybrid leak: ``<parameter name="role":`` (XML open tag broken into JSON key colon).
_PARAMETER_NAME_COLON_RE = re.compile(
    r'<parameter\s+name="([^"]+)"\s*:',
    re.IGNORECASE,
)
# After tag strip, top-level keys sometimes keep ``"tasks">`` instead of ``"tasks":``.
_JSON_KEY_GT_RE = re.compile(r'("(?:tasks|arguments|parameters|query|path|content)")\s*>')
# Residual angle-bracket junk stuck to identifiers (defense in depth after tag strip).
_STRAY_ANGLE_RE = re.compile(r"[<>]")


def sanitize_protocol_text(text: str) -> str:
    """Remove protocol tags from free text; collapse leftover whitespace runs lightly."""
    if not text:
        return text
    cleaned = _PROTOCOL_TAG_RE.sub("", text)
    # Do not strip all ``<>`` from prose (may contain comparisons); only collapse
    # whitespace left by removed tags.
    if cleaned != text:
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def sanitize_raw_tool_arguments(raw: str) -> str:
    """Clean protocol residue from raw tool-call argument JSON **before** parse.

    Narrow structural repairs only (tag strip + known hybrid key shapes). Does not
    invent missing fields or truncate bodies — if still invalid, ``json.loads`` fails
    honestly as before.
    """
    if not raw:
        return raw
    cleaned = _PARAMETER_NAME_COLON_RE.sub(r'"\1":', raw)
    cleaned = _PROTOCOL_TAG_RE.sub("", cleaned)
    cleaned = _JSON_KEY_GT_RE.sub(r"\1:", cleaned)
    if cleaned != raw:
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned


def sanitize_tool_name(name: str) -> str:
    """Normalize a tool name that may carry protocol-tag residue.

    ``web_query</longcat_arg_key>`` → ``web_query``. Empty after clean → ``""``.
    """
    raw = (name or "").strip()
    if not raw:
        return ""
    cleaned = _PROTOCOL_TAG_RE.sub("", raw)
    cleaned = _STRAY_ANGLE_RE.sub("", cleaned)
    cleaned = cleaned.strip().strip("\"'`")
    # Tool names are identifiers — keep only the leading token if junk trailed.
    if cleaned and not cleaned.replace("_", "").isalnum():
        m = re.match(r"^[A-Za-z_][\w]*", cleaned)
        if m:
            cleaned = m.group(0)
    return cleaned


def sanitize_tool_args(args: Any) -> Any:
    """Recursively sanitize string leaves in parsed tool arguments."""
    if isinstance(args, str):
        return sanitize_protocol_text(args)
    if isinstance(args, list):
        return [sanitize_tool_args(x) for x in args]
    if isinstance(args, dict):
        return {k: sanitize_tool_args(v) for k, v in args.items()}
    return args


def _delegate_payload_keys_present(args: dict[str, Any]) -> set[str]:
    """Which of ``_DELEGATE_PAYLOAD_KEYS`` are meaningfully present at this level."""
    present: set[str] = set()
    tasks = args.get("tasks")
    if isinstance(tasks, list) and bool(tasks):
        present.add("tasks")
    for key in ("playbook", "playbook_id"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            present.add(key)
    if "arguments" in _DELEGATE_PAYLOAD_KEYS and "arguments" in args:
        raw = args.get("arguments")
        if (isinstance(raw, str) and raw.strip()) or (isinstance(raw, dict) and raw):
            present.add("arguments")
    return present


def _inner_has_delegate_payload(inner: dict[str, Any]) -> bool:
    tasks = inner.get("tasks")
    if isinstance(tasks, list) and bool(tasks):
        return True
    for key in ("playbook", "playbook_id"):
        value = inner.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def unwrap_nested_delegate_arguments(args: Any) -> dict[str, Any] | None:
    """Narrow unwrap of double-wrapped delegate payload.

    Only when the top-level dict's sole meaningful payload key (among
    ``tasks`` / ``playbook`` / ``playbook_id`` / ``arguments``) is ``arguments``,
    and that value is a JSON object string or dict whose inner body carries
    non-empty ``tasks`` or a named ``playbook`` / ``playbook_id``. Returns the
    inner dict to use as replacement, or ``None`` when the shape does not match
    (including real top-level ``tasks`` plus an unrelated ``arguments`` key).
    """
    if not isinstance(args, dict):
        return None
    if _delegate_payload_keys_present(args) != {"arguments"}:
        return None
    raw = args.get("arguments")
    if isinstance(raw, str):
        try:
            inner: Any = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        inner = raw
    else:
        return None
    if not isinstance(inner, dict) or not _inner_has_delegate_payload(inner):
        return None
    return inner


def _json_escape_bare(text: str) -> str:
    """Escape a bare (unquoted) value so it can become a JSON string literal."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _looks_like_json_value_start(raw: str, pos: int) -> bool:
    """True when ``raw[pos:]`` already starts a normal JSON value."""
    if pos >= len(raw):
        return False
    ch = raw[pos]
    if ch in "\"{[":
        return True
    if ch in "-0123456789":
        return True
    for lit in ("true", "false", "null"):
        if raw.startswith(lit, pos):
            end = pos + len(lit)
            if end >= len(raw) or raw[end] in ",}] \t\n\r":
                return True
    return False


def _find_bare_value_end(raw: str, start: int) -> int:
    """End index of an unquoted property value (exclusive), before ``,``/``}``/``]``."""
    i = start
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == ",":
            k = i + 1
            while k < n and raw[k] in " \t\n\r":
                k += 1
            if k < n and raw[k] == '"':
                end = i
                while end > start and raw[end - 1] in " \t\n\r":
                    end -= 1
                return end
        elif ch in "}]":
            end = i
            while end > start and raw[end - 1] in " \t\n\r":
                end -= 1
            return end
        i += 1
    end = n
    while end > start and raw[end - 1] in " \t\n\r":
        end -= 1
    return end


def _quote_bare_handoff_string_fields(raw: str) -> str:
    """Quote known handoff string fields emitted as bare text (not JSON strings)."""
    out: list[str] = []
    i = 0
    n = len(raw)
    in_string = False
    escape = False
    while i < n:
        ch = raw[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            m = _HANDOFF_BARE_KEY_RE.match(raw, i)
            if m is not None and m.group(1) in _HANDOFF_BARE_STRING_KEYS:
                after = m.end()
                if after < n and not _looks_like_json_value_start(raw, after):
                    out.append(m.group(0))
                    value_end = _find_bare_value_end(raw, after)
                    out.append('"')
                    out.append(_json_escape_bare(raw[after:value_end]))
                    out.append('"')
                    i = value_end
                    continue
            in_string = True
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _close_truncated_json(raw: str) -> str:
    """Close an unclosed string / array / object at EOF — no invented fields."""
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in raw:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack and stack[-1] == ch:
            stack.pop()

    out = raw
    if in_string:
        if escape and out.endswith("\\"):
            out = out[:-1]
        out += '"'

    trimmed = out.rstrip()
    if trimmed.endswith(","):
        out = trimmed[:-1]

    while stack:
        out += stack.pop()
    return out


def salvage_handoff_raw_arguments(raw: str, *, tool_name: str = "") -> str | None:
    """Narrow salvage for handoff raw args after sanitize when ``json.loads`` fails.

    Repairs only:
    - known string fields (``summary`` / ``assumptions`` / ``next_steps``) with
      bare unquoted text → quote + escape;
    - truncated unclosed string / array / object brackets at EOF.

    Returns a JSON object string when salvage yields a loadable ``dict`` that
    differs from ``raw``; otherwise ``None`` (caller keeps honest parse failure).
    Non-``handoff`` tool names are ignored.
    """
    if (tool_name or "").strip() != "handoff":
        return None
    if not raw or not str(raw).strip():
        return None

    repaired = _quote_bare_handoff_string_fields(raw)
    repaired = _close_truncated_json(repaired)
    if repaired == raw:
        return None
    try:
        parsed: Any = json.loads(repaired)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return repaired
