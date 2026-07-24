"""Text accumulation helpers for multi-round ReAct output."""

from typing import Any

from agentcore.llm.provider.protocol import ToolCall

# Soft overlap trim needs a meaningful restatement — short accidental matches
# (punctuation, "1.", "好的") must not erase a real continuation.
_MIN_OVERLAP = 12
_MAX_OVERLAP = 400


def tool_calls_to_dicts(tool_calls: list[ToolCall] | None) -> list[dict[str, Any]]:
    """Serialize a round's tool calls for the ``llm_call`` fact (§8.3).

    The window fold rebuilds the assistant message from this, so it mirrors the
    OpenAI/transcript shape (``runs.serialize._tool_call_to_dict``) exactly — id +
    type + function(name, arguments) — keeping the facts module free of an
    ``llm.protocol`` import on the read side.
    """
    if not tool_calls:
        return []
    return [
        {
            "id": tc.id,
            "type": tc.type,
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        for tc in tool_calls
    ]


def _trim_suffix_prefix_overlap(left: str, right: str) -> str:
    """Drop a leading chunk of ``right`` that equals a trailing chunk of ``left``."""
    max_check = min(len(left), len(right), _MAX_OVERLAP)
    for size in range(max_check, _MIN_OVERLAP - 1, -1):
        if left.endswith(right[:size]):
            return right[size:].lstrip()
    return right


def join_segments(acc: str, new: str) -> str:
    """Append a round's deliverable text as a coherent paragraph seam.

    Each kept ReAct segment (终止轮前交付、续跑续段、force_finalize 收尾) is a distinct
    write that must read as one persisted交付. Raw concatenation made a pre-tool lead-in
    (e.g. ending in "：") run into the post-resume continuation; a blank-line join alone
    still left restated openings. Normalize edges, drop a restated prefix when the new
    segment restarts the prior close, then insert ``\\n\\n`` between non-empty segments.
    Live stream deltas are unaffected — this only shapes the accumulated ``content``.
    """
    if not acc:
        return new
    if not new:
        return acc

    left = acc.rstrip()
    right = new.lstrip()
    if not left:
        return new
    if not right:
        return acc

    # Same last paragraph restated at the start of ``right`` → splice the tail.
    last_para = left.rsplit("\n\n", 1)[-1].strip()
    if len(last_para) >= _MIN_OVERLAP and right.startswith(last_para):
        remainder = right[len(last_para) :]
        if not remainder.strip():
            return left
        # List / line continuation (single \\n) stays tight; a new paragraph keeps \\n\\n.
        if remainder.startswith("\n") and not remainder.startswith("\n\n"):
            return left + remainder
        return f"{left}\n\n{remainder.lstrip()}"

    right = _trim_suffix_prefix_overlap(left, right)
    if not right:
        return left
    return f"{left}\n\n{right}"


def deliverable_continuity_instruction(*, prior_deliverable: str) -> str:
    """Steer the next answer round to continue an already-kept deliverable.

    Used at force_finalize / resume when ``final_content`` / pre-pause text will be
    joined into the persisted终稿. Not a rewrite pass — one short ``[系统提示]`` so the
    model writes a natural continuation instead of a second standalone essay.
    """
    preview = prior_deliverable.strip()
    if len(preview) > 600:
        preview = preview[:600].rstrip() + "…"
    return (
        "[系统提示] 本回合对用户可见的交付正文已有前文（将与你的续写拼接为同一篇持久化终稿）。"
        "请自然衔接续写：不要重复开场白，不要复述已交付内容，不要另起一篇独立答卷。"
        f"已交付前文如下（仅供衔接参考）：\n---\n{preview}\n---"
    )
