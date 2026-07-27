"""Deep conversation transcript export (messages + turn_journal → markdown).

Used by Worker ``search_conversations`` / ``read_conversation`` and by
server-side conversation-attachment deep reads (``_build_attachment_context``).
Deliberately separate from:

- ``history.py`` — shallow user/assistant bodies for the LLM working window
- ``export.py`` — user-facing shallow Q&A download

Cross-session log access needs the full process layer (tools / debate / evidence).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agentcore.db.models import Conversation, Message
from agentcore.runtime.journal import KIND_TURN_END

# Single-chunk hard ceiling for ``read_conversation`` (跨会话对话日志访问定案).
# Callers must set ``ToolResult.output_limit`` ≥ returned chunk length — never lean
# on the default 4000 head+tail truncate.
MAX_CHUNK_CHARS = 100_000

# Snippet length for search rows.
SEARCH_SNIPPET_CHARS = 240

_EXPORTED_ROLES = frozenset({"user", "assistant"})

# Journal kinds we deliberately skip (noise / cost / followups).
_SKIP_KINDS = frozenset(
    {
        "followups",
        "cost",
        "feedback",
        "citations",  # rendered from message.citations instead
        "evidence_ledger",  # rendered from message.evidence_ledger instead
    }
)

_TOOL_KINDS = frozenset({"tool_use_start", "tool_use_end", "tool_progress"})
_DEBATE_PREFIX = "debate_"


@dataclass(frozen=True)
class LogChunk:
    """One page of a deep transcript (cursor-continuable)."""

    title: str
    conversation_id: str
    transcript: str
    truncated: bool
    next_cursor: str | None
    started_at: str | None
    ended_at: str | None
    message_count: int
    char_offset: int
    total_chars: int


def _fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _jsonish(value: Any, *, limit: int = 2000) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        raw = str(value)
    return _clip(raw, limit)


def _render_journal_entry(entry: Mapping[str, Any]) -> list[str]:
    """Render one journal fact into markdown lines (may be empty = skip)."""
    kind = str(entry.get("kind") or "")
    if not kind or kind in _SKIP_KINDS:
        return []
    payload = entry.get("payload") or {}
    if not isinstance(payload, Mapping):
        payload = {}

    if kind == "tool_use_start":
        name = str(payload.get("tool_name") or payload.get("name") or "tool")
        args = payload.get("arguments")
        lines = [f"#### Tool: {name}", ""]
        if args is not None:
            lines.append("```")
            lines.append(_jsonish(args))
            lines.append("```")
            lines.append("")
        return lines

    if kind == "tool_use_end":
        name = str(payload.get("tool_name") or payload.get("name") or "tool")
        success = payload.get("success")
        status = "ok" if success is True else ("fail" if success is False else "")
        head = f"#### Tool result: {name}"
        if status:
            head += f" ({status})"
        lines = [head, ""]
        output = payload.get("result")
        if output is None:
            output = payload.get("output")
        if output is not None:
            body = output if isinstance(output, str) else _jsonish(output, limit=8000)
            lines.append(_clip(str(body), 8000))
            lines.append("")
        err = payload.get("error")
        if err:
            lines.append(f"*error:* {_clip(str(err), 500)}")
            lines.append("")
        return lines

    if kind == "tool_progress":
        phase = payload.get("phase") or payload.get("message") or ""
        if not phase:
            return []
        return [f"- tool progress: {_clip(str(phase), 240)}", ""]

    if kind.startswith(_DEBATE_PREFIX) or kind in {
        "debate_result",
        "debate_round",
        "debate_round_started",
        "debate_pretrial_started",
        "debate_pretrial_orders",
        "debate_pretrial_progress",
        "debate_pretrial_completed",
    }:
        lines = ["#### Debate", ""]
        summary = (
            payload.get("summary")
            or payload.get("opening")
            or payload.get("verdict")
            or payload.get("text")
            or payload.get("message")
        )
        lines.append(f"- `{kind}`")
        if summary:
            lines.append(_clip(str(summary), 2000))
        else:
            # Compact payload peek — avoid dumping huge debate state.
            peek_keys = ("round", "side", "side_key", "status", "form")
            bits = [
                f"{k}={payload.get(k)}" for k in peek_keys if payload.get(k) is not None
            ]
            if bits:
                lines.append("- " + "; ".join(bits))
        lines.append("")
        return lines

    if kind == KIND_TURN_END:
        fr = payload.get("finish_reason")
        err = payload.get("error")
        if not fr and not err:
            return []
        note = "finish_reason=" + str(fr) if fr else "turn ended"
        if err:
            note += f"; error={_clip(str(err), 300)}"
        return [f"*system:* {note}", ""]

    if kind.startswith("process_") or kind.startswith("run_process_"):
        label = kind.removeprefix("process_").removeprefix("run_process_")
        text = payload.get("text") or payload.get("summary") or payload.get("kind") or label
        run_id = payload.get("run_id")
        prefix = f"[{run_id}] " if run_id else ""
        return [f"- {prefix}{_clip(str(text), 400)}", ""]

    # Collaboration / delegate short bullets (run_plan, run_started, …).
    if kind in {
        "run_plan",
        "run_started",
        "run_completed",
        "run_failed",
        "graph_append",
        "plan_revised",
        "round_boundary",
    }:
        summary = (
            payload.get("task_summary")
            or payload.get("summary")
            or payload.get("role")
            or kind
        )
        return [f"- `{kind}`: {_clip(str(summary), 400)}", ""]

    return []


def _render_message_block(
    msg: Message,
    journal: Sequence[Mapping[str, Any]] | None,
) -> str:
    """One user/assistant message as markdown (journal process before assistant body)."""
    role = msg.role or ""
    if role not in _EXPORTED_ROLES:
        return ""
    lines: list[str] = []
    if role == "user":
        lines.append("### User")
        lines.append("")
        body = (msg.content or "").strip()
        if body:
            lines.append(body)
            lines.append("")
        # Attachment names only (no binary dump).
        for att in msg.attachments or []:
            if not isinstance(att, Mapping):
                continue
            name = att.get("name") or att.get("path") or "attachment"
            lines.append(f"- attachment: {name}")
        if msg.attachments:
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # assistant
    lines.append("### Assistant")
    lines.append("")
    if journal:
        for entry in journal:
            lines.extend(_render_journal_entry(entry))

    reasoning = (msg.reasoning_content or "").strip()
    if reasoning:
        lines.append("#### Thinking")
        lines.append("")
        lines.append(_clip(reasoning, 12_000))
        lines.append("")

    content = (msg.content or "").strip()
    if content:
        lines.append(content)
        lines.append("")

    evidence = msg.evidence_ledger if isinstance(msg.evidence_ledger, list) else []
    if evidence:
        lines.append("#### Evidence")
        lines.append("")
        for item in evidence[:40]:
            if not isinstance(item, Mapping):
                continue
            eid = item.get("id") or ""
            title = item.get("title") or item.get("url") or ""
            lines.append(f"- {eid} {title}".strip())
        lines.append("")

    citations = msg.citations if isinstance(msg.citations, list) else []
    if citations:
        lines.append("#### Citations")
        lines.append("")
        for item in citations[:40]:
            if not isinstance(item, Mapping):
                continue
            title = item.get("title") or ""
            url = item.get("url") or ""
            lines.append(f"- [{title}]({url})" if url else f"- {title}")
        lines.append("")

    usage = msg.usage if isinstance(msg.usage, dict) else None
    if usage and usage.get("status") in {"error", "cancelled", "interrupted"}:
        lines.append(f"*system:* turn status={usage.get('status')}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_conversation_log(
    conversation: Conversation,
    messages: Sequence[Message],
    journal_map: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> str:
    """Full deep markdown transcript for one conversation (no chunking)."""
    journal_map = journal_map or {}
    title = (conversation.title or "").strip() or "未命名对话"
    parts: list[str] = [
        f"# {title}",
        "",
        f"- conversation_id: `{conversation.id}`",
        f"- created_at: {_fmt_ts(conversation.created_at) or '—'}",
        f"- updated_at: {_fmt_ts(conversation.updated_at) or '—'}",
        "",
    ]
    for msg in messages:
        if (msg.role or "") not in _EXPORTED_ROLES:
            continue
        journal = journal_map.get(msg.id) if msg.role == "assistant" else None
        block = _render_message_block(msg, journal)
        if block.strip():
            parts.append(block)
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def encode_cursor(char_offset: int) -> str:
    return f"c:{max(0, int(char_offset))}"


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    raw = str(cursor).strip()
    if raw.startswith("c:"):
        try:
            return max(0, int(raw[2:]))
        except ValueError:
            return 0
    # Be forgiving about a bare integer.
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def chunk_transcript(
    full: str,
    *,
    conversation: Conversation,
    messages: Sequence[Message],
    cursor: str | None = None,
    max_chars: int | None = None,
) -> LogChunk:
    """Slice ``full`` at ``cursor`` into a ≤ ``max_chars`` page with ``next_cursor``."""
    limit = max_chars if max_chars is not None else MAX_CHUNK_CHARS
    limit = max(1, min(int(limit), MAX_CHUNK_CHARS))
    offset = decode_cursor(cursor)
    total = len(full)
    if offset > total:
        offset = total
    end = min(total, offset + limit)
    piece = full[offset:end]
    truncated = end < total
    next_cursor = encode_cursor(end) if truncated else None
    started = None
    ended = None
    visible = [m for m in messages if (m.role or "") in _EXPORTED_ROLES]
    if visible:
        started = _fmt_ts(visible[0].created_at)
        ended = _fmt_ts(visible[-1].created_at)
    return LogChunk(
        title=(conversation.title or "").strip() or "未命名对话",
        conversation_id=conversation.id,
        transcript=piece,
        truncated=truncated,
        next_cursor=next_cursor,
        started_at=started,
        ended_at=ended,
        message_count=len(visible),
        char_offset=offset,
        total_chars=total,
    )


def search_snippet_from_messages(messages: Sequence[Message], query: str) -> str | None:
    """Pick a short content snippet matching ``query`` (or latest user text)."""
    q = (query or "").strip().lower()
    for msg in reversed(list(messages)):
        body = (msg.content or "").strip()
        if not body:
            continue
        if q and q in body.lower():
            return _clip(body, SEARCH_SNIPPET_CHARS)
    for msg in reversed(list(messages)):
        if msg.role == "user" and (msg.content or "").strip():
            return _clip(msg.content or "", SEARCH_SNIPPET_CHARS)
    return None
