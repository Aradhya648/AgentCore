"""Text-shaping primitives — a leaf layer below tools/runtime (zero project deps).

``truncate_head_tail`` is the ONE head+tail truncation used wherever an over-budget
string must be cut for the model: it keeps BOTH ends with an elision marker between, so
trailing details (金额 / 法条编号 / 文件末尾的命中) survive — a head-only cut silently
drops them. Extracted here once a third site needed it (``ToolResult`` model-facing
output, ``runs/fidelity`` dep injection, ``conversation/compaction`` summary safety net):
one mechanism, not three drifting copies. Each caller binds a domain-appropriate
``marker`` and owns its char budget (the budgets live with the callers).
"""

from __future__ import annotations

# Generic elision marker (the framing/tail-survival cut). Callers with a domain voice
# (e.g. compaction's「摘要过长」) pass their own; everyone else takes this default.
DEFAULT_ELISION_MARKER = "\n\n……（中间省略，已保留首尾）……\n\n"


def truncate_head_tail(content: str, limit: int, *, marker: str = DEFAULT_ELISION_MARKER) -> str:
    """Trim ``content`` to ``limit`` chars, keeping head + tail with ``marker`` between.

    Returns ``content`` unchanged when it already fits, ``""`` when ``limit <= 0``. The
    head gets ~3/5 of the surviving budget (framing) while a real tail still survives.
    When the budget is too small to fit even the marker, falls back to a head-only cut
    plus an ellipsis (a degenerate case real budgets never hit).
    """
    if limit <= 0:
        return ""
    if len(content) <= limit:
        return content
    keep = limit - len(marker)
    if keep <= 0:
        return content[:limit].rstrip() + "…"
    head = keep * 3 // 5
    tail = keep - head
    return content[:head].rstrip() + marker + content[len(content) - tail :].lstrip()


def clip_preview(text: str, limit: int) -> str:
    """Single-line, head-clipped preview of ``text`` for a log field.

    Collapses all whitespace runs to single spaces (so a multi-line prompt / task /
    feedback fits one JSON log field), then head-clips to ``limit`` with an ellipsis.
    For logs only — a bounded snippet to triage 「问了什么 / 为什么这么决策」, never the
    full 正文 (logging.mdc 铁律). The canonical log-preview shaper (conversation previews
    and the orchestration decision logs share it, so they don't drift).
    """
    collapsed = " ".join((text or "").split())
    return collapsed[:limit] + "…" if len(collapsed) > limit else collapsed
