"""Strip vendor tool-call protocol tags leaking into tool names / args / prose.

Some OpenAI-compatible providers (e.g. LongCat) occasionally emit residual XML-like
markers such as ``</longcat_arg_key>`` or ``<longcat_tool_call>`` inside tool names,
argument strings, or handoff summary text. Clean at the tool-exec / harvest seam so
illegal names become retryable and briefs stay readable — no provider-specific adapter.

Also used **before** ``json.loads`` on raw tool-call arguments: models sometimes mix
Anthropic-style ``<parameter>`` / ``<object>`` fragments into OpenAI JSON args, which
would otherwise hard-fail as ``args_parse_failed``.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "sanitize_protocol_text",
    "sanitize_raw_tool_arguments",
    "sanitize_tool_args",
    "sanitize_tool_name",
]

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
