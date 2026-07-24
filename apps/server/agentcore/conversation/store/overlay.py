"""Read-path stream_state overlay for in-flight turns (流式回复持久化 §3.3).

终态事实 > stream_state > 无. Criterion = ``usage.status`` (not ``messages.finish_reason``).
Paused rows keep pause-snapshot columns — never overwritten by possibly-stale segments.
"""

from __future__ import annotations

from typing import Any

from agentcore.conversation.store.merge import (
    MESSAGE_STATUS_RUNNING,
    pick_monotonic_content,
)
from agentcore.runtime.events.stream_checkpointer import (
    CHANNEL_CAPTAIN_CONTENT,
    CHANNEL_CAPTAIN_REASONING,
    parse_run_channel,
)
from agentcore.runtime.events.types import EventType


def should_overlay_stream_state(usage: dict[str, Any] | None) -> bool:
    """True when GET messages/recovery may fill fields from ``turn_stream_state``."""
    if not usage:
        return False
    if usage.get("paused"):
        return False
    return usage.get("status") == MESSAGE_STATUS_RUNNING


def segments_by_channel(segments: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(s["channel"]): str(s.get("text") or "")
        for s in segments
        if s.get("channel")
    }


def overlay_message_fields(
    *,
    content: str | None,
    reasoning_content: str | None,
    segments: list[dict[str, Any]],
    usage: dict[str, Any] | None,
    skip_captain_content: bool = False,
) -> tuple[str | None, str | None]:
    """Return ``(content, reasoning)`` after applying captain channel overlays.

    ``skip_captain_content``: when the journal already has ``process_*`` narration
    **or** the turn is structured (tools / team / process lane), do **not** pour
    ``captain:content`` into ``messages.content`` (deliverable_only — mid-run
    refresh restores process from journal, not the content column). Prose-only
    turns keep the segment accelerate / salvage path.
    """
    if not should_overlay_stream_state(usage) or not segments:
        return content, reasoning_content
    by_ch = segments_by_channel(segments)
    cap_content = by_ch.get(CHANNEL_CAPTAIN_CONTENT)
    cap_reasoning = by_ch.get(CHANNEL_CAPTAIN_REASONING)
    out_content = content
    out_reasoning = reasoning_content
    if cap_content and not skip_captain_content:
        out_content = pick_monotonic_content(content, cap_content)
    if cap_reasoning:
        out_reasoning = pick_monotonic_content(reasoning_content, cap_reasoning)
    return out_content, out_reasoning


def overlay_runs_with_segments(
    runs: dict[str, Any] | None,
    segments: list[dict[str, Any]],
    *,
    usage: dict[str, Any] | None,
    agent_run_ids: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Synthesize partial worker deltas from segments for runs lacking ``message_final``.

    Same shape as journal fold's message_final → single-block delta splice. Only applies
    while the turn is still ``running`` (non-paused).
    """
    if not should_overlay_stream_state(usage) or not segments:
        return runs

    by_ch = segments_by_channel(segments)
    partial: dict[str, dict[str, str]] = {}
    for channel, text in by_ch.items():
        parsed = parse_run_channel(channel)
        if parsed is None or not text:
            continue
        run_id, kind = parsed
        slot = partial.setdefault(run_id, {"content": "", "reasoning": ""})
        if kind == "output":
            slot["content"] = text
        else:
            slot["reasoning"] = text
    if not partial:
        return runs

    # Prefer journal-derived agent_id map; fall back to scanning runs.events.
    ids = dict(agent_run_ids or {})
    events: list[dict[str, Any]] = list((runs or {}).get("events") or [])
    if not ids:
        for ev in events:
            if ev.get("type") != EventType.RUN_STARTED.value:
                continue
            payload = ev.get("payload") or {}
            if payload.get("kind") == "agent":
                rid = payload.get("run_id")
                if rid:
                    ids[rid] = payload.get("agent_id") or ""

    # Drop runs that already have a terminal event with spliced content from message_final
    # — only fill runs that still lack output in the projected events.
    covered: set[str] = set()
    for ev in events:
        if ev.get("type") in (
            EventType.RUN_OUTPUT_DELTA.value,
            EventType.RUN_REASONING_DELTA.value,
        ):
            rid = (ev.get("payload") or {}).get("run_id")
            if rid:
                covered.add(rid)

    need = {rid: texts for rid, texts in partial.items() if rid not in covered and rid in ids}
    if not need:
        return runs

    # In-flight workers have no terminal yet — append one-block deltas (same shape as
    # message_final synthesis) so the client fold rebuilds partial 输出/思考.
    extra: list[dict[str, Any]] = []
    for rid, texts in need.items():
        agent_id = ids.get(rid) or ""
        if texts.get("reasoning"):
            extra.append(
                {
                    "type": EventType.RUN_REASONING_DELTA.value,
                    "payload": {
                        "run_id": rid,
                        "agent_id": agent_id,
                        "delta": texts["reasoning"],
                    },
                    "timestamp": None,
                }
            )
        if texts.get("content"):
            extra.append(
                {
                    "type": EventType.RUN_OUTPUT_DELTA.value,
                    "payload": {
                        "run_id": rid,
                        "agent_id": agent_id,
                        "delta": texts["content"],
                    },
                    "timestamp": None,
                }
            )

    out = dict(runs or {})
    out["events"] = events + extra
    return out
