"""Newline-tolerant text replace for workspace ``replace`` / ``str_replace``.

Algorithm (shared with Desktop ``textReplace.ts``):

1. Exact byte match first — on hit, replace in place (byte-faithful).
2. If zero hits: normalize file + ``old``/``new`` to ``\\n``, match/replace,
   then restore ``\\r\\n`` when the original file contained ``\\r\\n``
   (same eol口径 as ``read_for_edit`` / ``write_text_cas``).
3. Still zero → no match; ``>1`` without ``all_`` → ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextReplaceOk:
    content: str
    count: int
    first_line: int | None


@dataclass(frozen=True)
class TextReplaceNoMatch:
    pass


@dataclass(frozen=True)
class TextReplaceAmbiguous:
    count: int


type TextReplaceResult = TextReplaceOk | TextReplaceNoMatch | TextReplaceAmbiguous


def _to_lf(s: str) -> str:
    return s.replace("\r\n", "\n")


def apply_text_replace(content: str, old: str, new: str, *, all_: bool) -> TextReplaceResult:
    """Apply ``old``→``new`` on ``content``; see module docstring for EOL rules."""
    exact = _try_replace(content, old, new, all_=all_)
    if not isinstance(exact, TextReplaceNoMatch):
        return exact

    eol_crlf = "\r\n" in content
    norm_content = _to_lf(content)
    norm_old = _to_lf(old)
    norm_new = _to_lf(new)
    # Normalization was a no-op for every string → exact path already covered this.
    if norm_content == content and norm_old == old and norm_new == new:
        return TextReplaceNoMatch()

    fallback = _try_replace(norm_content, norm_old, norm_new, all_=all_)
    if isinstance(fallback, TextReplaceOk) and eol_crlf:
        return TextReplaceOk(
            content=fallback.content.replace("\n", "\r\n"),
            count=fallback.count,
            first_line=fallback.first_line,
        )
    return fallback


def _try_replace(content: str, old: str, new: str, *, all_: bool) -> TextReplaceResult:
    count = content.count(old)
    if count == 0:
        return TextReplaceNoMatch()
    if count > 1 and not all_:
        return TextReplaceAmbiguous(count)

    if all_:
        return TextReplaceOk(content.replace(old, new), count, None)

    idx = content.find(old)
    new_content = content.replace(old, new, 1)
    first_line = content[:idx].count("\n") + 1
    return TextReplaceOk(new_content, 1, first_line)
