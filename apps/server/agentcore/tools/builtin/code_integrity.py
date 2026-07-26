"""Code-file structure gate for ``file_write`` / ``file_append``.

Catches the common multi-agent failure mode: a TypeScript/JavaScript (etc.)
file is marked「完整落盘」but ends mid-class with missing ``}`` (see product
trace whiteboard MVP →「修复下」missing braces).

Skeleton writes (``<!-- SECTION: -->`` / ``<!-- OUTLINE -->``) are exempt so
Artifact-first fill-in still works; callers skip this gate when skeleton
markers are present. Omission-marker hard rejects for code paths live in
``file_ops`` (reuse ``has_omission_marker``).
"""

from __future__ import annotations

from pathlib import PurePosixPath

# Brace-delimited source — the defect class in the whiteboard log.
_BRACE_CODE_SUFFIXES = frozenset(
    {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".css",
        ".scss",
        ".less",
        ".vue",
        ".svelte",
    }
)

_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSING = frozenset(_OPEN_TO_CLOSE.values())


def is_brace_code_path(path: str) -> bool:
    """True when ``path`` looks like brace-delimited application source."""
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    return suffix in _BRACE_CODE_SUFFIXES


def _scan_delimiter_balance(content: str) -> tuple[str, str] | None:
    """Return ``(kind, detail)`` when ``{}`` / ``[]`` / ``()`` are unbalanced.

    Ignores delimiters inside ``//`` / ``/* */`` comments and ``'`` / ``"`` /
    `` ` `` spans (template bodies are opaque — ``${…}`` not interpreted).
    Good enough to catch truncated class/function files; not a full parser.
    """
    stack: list[tuple[str, int]] = []  # (expected closer, line)
    i = 0
    n = len(content)
    line = 1
    in_line_comment = False
    in_block_comment = False
    string_quote: str | None = None

    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""

        if ch == "\n":
            line += 1
            in_line_comment = False
            i += 1
            continue

        if in_line_comment:
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if string_quote is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == string_quote:
                string_quote = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ("'", '"', "`"):
            string_quote = ch
            i += 1
            continue

        if ch in _OPEN_TO_CLOSE:
            stack.append((_OPEN_TO_CLOSE[ch], line))
            i += 1
            continue

        if ch in _CLOSING:
            if not stack:
                return (
                    "extra_close",
                    f"第 {line} 行出现多余的闭合符 `{ch}`",
                )
            expected, open_line = stack.pop()
            if ch != expected:
                return (
                    "mismatch",
                    f"第 {line} 行闭合符 `{ch}` 与第 {open_line} 行的开符不匹配"
                    f"（期望 `{expected}`）",
                )
            i += 1
            continue

        i += 1

    if stack:
        expected, open_line = stack[-1]
        opener = next(k for k, v in _OPEN_TO_CLOSE.items() if v == expected)
        return (
            "unclosed",
            f"第 {open_line} 行的 `{opener}` 未闭合（缺 `{expected}`；共 {len(stack)} 处未闭合）",
        )
    return None


def code_structure_rejection(path: str, content: str) -> str | None:
    """Model-facing hard-reject text, or ``None`` if the write looks structurally ok."""
    if not is_brace_code_path(path):
        return None
    if not (content or "").strip():
        return None
    issue = _scan_delimiter_balance(content)
    if issue is None:
        return None
    _kind, detail = issue
    return (
        f"拒绝写入代码文件 `{path}`：括号/方括号/圆括号结构不完整（{detail}）。"
        "这通常是生成被截断（类/函数末尾缺 `}`）。"
        "请补全后再 file_write，或先短骨架（含 `<!-- SECTION: -->`）再按节填空；"
        "已有残缺成品请用 str_replace 就地补全，勿整文件覆盖残稿。"
    )


def code_omission_rejection(path: str) -> str:
    """Hard-reject copy when a brace-code path contains omission markers."""
    return (
        f"拒绝写入代码文件 `{path}`：正文含省略标记（如「中间省略」/ truncated）。"
        "代码交付必须是可解析的完整正文，禁止用省略占位冒充落盘。"
    )
