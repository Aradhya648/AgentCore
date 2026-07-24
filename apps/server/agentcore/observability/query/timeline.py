"""High-level timeline / trace queries over JSONL + conversation store."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentcore.observability.query.jsonl import (
    JsonlLogSource,
    ReadFilter,
    ReadStats,
    iter_events,
    load_events,
)
from agentcore.observability.query.store import ConversationStore

_LOG_NOISE_KEYS = (
    "type",
    "timestamp",
    "event",
    "level",
    "logger",
    "request_id",
    "method",
    "path",
)
_TURN_SPINE_EVENTS = frozenset({"chat.turn_start", "chat.turn_complete"})


@dataclass
class TimelineQueryResult:
    """Structured timeline payload (human formatter or ``--json``)."""

    mode: str  # conversation | trace | recent
    conversation: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    log_events: list[dict[str, Any]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str | None = None
    spine_events: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def _project_log_event(obj: dict[str, Any], *, drop_field: str | None = None) -> dict[str, Any]:
    skip = set(_LOG_NOISE_KEYS)
    if drop_field:
        skip.add(drop_field)
    return {
        "type": "log",
        "timestamp": obj.get("timestamp", ""),
        "event": obj.get("event", ""),
        "level": obj.get("level", ""),
        **{k: v for k, v in obj.items() if k not in skip},
    }


def load_log_events(
    value: str,
    field: str = "conversation_id",
    *,
    log_file: Path,
    since: datetime | None = None,
) -> tuple[list[dict[str, Any]], ReadStats]:
    """Load projected log lines whose ``field`` equals ``value``.

    Exact-ID loads always include synthetic ``traffic=eval|test`` lines: one
    trace/conversation belongs entirely to a single traffic class, so filtering
    here could only make the whole result vanish (a debugging trap). Callers
    surface the class via :func:`detect_traffic` instead.
    """
    filt = ReadFilter(
        since=since,
        include_synthetic=True,
        field_equals=(field, value),
    )
    raw, stats = load_events(log_file, filt)
    projected = [_project_log_event(obj, drop_field=field) for obj in raw]
    return projected, stats


def detect_traffic(log_events: list[dict[str, Any]]) -> str | None:
    """Traffic class of an exact-ID result (``eval`` / ``test``), None = real."""
    for item in log_events:
        traffic = item.get("traffic")
        if traffic is not None:
            return str(traffic)
    return None


def load_conversation_spine_events(
    conversation_id: str,
    *,
    log_file: Path,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Load chat.turn_start / chat.turn_complete for conversation context."""
    filt = ReadFilter(
        since=since,
        include_synthetic=True,
        field_equals=("conversation_id", conversation_id),
    )
    events: list[dict[str, Any]] = []
    for obj in iter_events(JsonlLogSource(log_file), filt):
        event = obj.get("event", "")
        if event not in _TURN_SPINE_EVENTS:
            continue
        events.append(
            {
                "timestamp": obj.get("timestamp", ""),
                "event": event,
                "trace_id": obj.get("trace_id", ""),
                "preview": obj.get("preview", ""),
                "delegated": obj.get("delegated"),
            }
        )
    return events


def extract_conversation_id(log_events: list[dict[str, Any]]) -> str | None:
    for item in log_events:
        cid = item.get("conversation_id")
        if cid:
            return str(cid)
    return None


async def query_conversation_timeline(
    conversation_id: str,
    *,
    store: ConversationStore,
    log_file: Path,
    since: datetime | None = None,
) -> TimelineQueryResult:
    """Exact-ID query: synthetic traffic is always included; class in meta.traffic."""
    conv = await store.get_conversation(conversation_id)
    if conv is None:
        return TimelineQueryResult(
            mode="conversation",
            meta={"error": "conversation_not_found", "conversation_id": conversation_id},
        )
    messages = await store.get_messages(conversation_id)
    log_events, stats = load_log_events(
        conversation_id,
        field="conversation_id",
        log_file=log_file,
        since=since,
    )
    return TimelineQueryResult(
        mode="conversation",
        conversation=conv,
        messages=messages,
        log_events=log_events,
        meta={
            "conversation_id": conversation_id,
            "traffic": detect_traffic(log_events),
            "bad_lines": stats.bad_lines,
            "files": [str(p) for p in stats.files],
        },
    )


async def query_trace(
    trace_id: str,
    *,
    log_file: Path,
    since: datetime | None = None,
) -> TimelineQueryResult:
    """Exact-ID query: synthetic traffic is always included; class in meta.traffic."""
    log_events, stats = load_log_events(
        trace_id,
        field="trace_id",
        log_file=log_file,
        since=since,
    )
    conv_id = extract_conversation_id(log_events)
    spine: list[dict[str, Any]] = []
    if conv_id:
        spine = load_conversation_spine_events(
            conv_id,
            log_file=log_file,
            since=since,
        )
    return TimelineQueryResult(
        mode="trace",
        trace_id=trace_id,
        log_events=log_events,
        spine_events=spine,
        meta={
            "conversation_id": conv_id,
            "traffic": detect_traffic(log_events),
            "bad_lines": stats.bad_lines,
            "files": [str(p) for p in stats.files],
        },
    )


async def query_recent(
    n: int,
    *,
    store: ConversationStore,
) -> TimelineQueryResult:
    recent = await store.list_recent(n)
    return TimelineQueryResult(mode="recent", recent=recent, meta={"n": n})
