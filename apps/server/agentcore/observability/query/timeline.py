"""High-level timeline / trace queries over JSONL + conversation store."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentcore.observability.query.decision_spine import build_decision_spine
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
# turn_spine = session directory of chat.turn_start|complete (NOT decision_spine).
_TURN_SPINE_EVENTS = frozenset({"chat.turn_start", "chat.turn_complete"})


@dataclass
class TimelineQueryResult:
    """Structured timeline payload (human formatter or ``--json``).

    Default (non-raw) consumers should read ``decision_spine`` /
    ``decision_spines``. ``log_events`` + ``spine_events`` (turn_spine) remain for
    ``--raw`` firehose mode.
    """

    mode: str  # conversation | trace | recent
    conversation: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    log_events: list[dict[str, Any]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str | None = None
    spine_events: list[dict[str, Any]] = field(default_factory=list)  # turn_spine
    decision_spine: dict[str, Any] | None = None
    decision_spines: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self, *, raw: bool = False) -> dict[str, Any]:
        if raw:
            payload = asdict(self)
            # Raw = full firehose; decision_* still present but secondary.
            return payload
        if self.mode == "recent":
            return {
                "mode": self.mode,
                "recent": self.recent,
                "meta": self.meta,
            }
        if self.mode == "trace":
            return {
                "mode": self.mode,
                "decision_spine": self.decision_spine,
                "meta": self.meta,
            }
        # conversation
        return {
            "mode": self.mode,
            "conversation": self.conversation,
            "messages": self.messages,
            "decision_spines": self.decision_spines,
            "meta": self.meta,
        }


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
    """Load turn_spine: chat.turn_start / chat.turn_complete for conversation context.

    This is the session turn directory — **not** the product ``decision_spine``.
    """
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


def _group_events_by_trace(
    log_events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for ev in log_events:
        tid = ev.get("trace_id")
        if not tid:
            continue
        groups.setdefault(str(tid), []).append(ev)
    return groups


async def _build_spine_for_trace(
    trace_id: str,
    log_events: list[dict[str, Any]],
    *,
    store: ConversationStore | None,
    conversation_id: str | None,
    traffic: str | None,
    jsonl_gap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = None
    cost = None
    if store is not None:
        metrics = await store.get_turn_metrics_by_trace(trace_id)
        cost = await store.get_cost_by_trace(trace_id)
    return build_decision_spine(
        log_events,
        trace_id=trace_id,
        conversation_id=conversation_id,
        turn_metrics=metrics,
        cost_events=cost,
        traffic=traffic,
        jsonl_gap=jsonl_gap,
    )


async def query_conversation_timeline(
    conversation_id: str,
    *,
    store: ConversationStore,
    log_file: Path,
    since: datetime | None = None,
    jsonl_gap_for: dict[str, dict[str, Any] | None] | None = None,
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
    traffic = detect_traffic(log_events)
    by_trace = _group_events_by_trace(log_events)
    # Prefer turn_metrics order when available; else event order.
    metrics_rows = await store.get_turn_metrics_for_conversation(conversation_id)
    ordered_tids: list[str] = []
    seen: set[str] = set()
    for row in metrics_rows:
        tid = row.get("trace_id")
        if tid and tid not in seen:
            ordered_tids.append(str(tid))
            seen.add(str(tid))
    for tid in by_trace:
        if tid not in seen:
            ordered_tids.append(tid)
            seen.add(tid)

    spines: list[dict[str, Any]] = []
    drift_l2_any = False
    for tid in ordered_tids:
        evs = by_trace.get(tid, [])
        gap = (jsonl_gap_for or {}).get(tid)
        spine = await _build_spine_for_trace(
            tid,
            evs,
            store=store,
            conversation_id=conversation_id,
            traffic=traffic,
            jsonl_gap=gap,
        )
        if (spine.get("health") or {}).get("drift_l2", {}).get("compared") and not (
            spine.get("health") or {}
        ).get("drift_l2", {}).get("ok"):
            drift_l2_any = True
        spines.append(spine)

    return TimelineQueryResult(
        mode="conversation",
        conversation=conv,
        messages=messages,
        log_events=log_events,
        decision_spines=spines,
        meta={
            "conversation_id": conversation_id,
            "traffic": traffic,
            "bad_lines": stats.bad_lines,
            "files": [str(p) for p in stats.files],
            "decision_spine_count": len(spines),
            "drift_l2": "mismatch" if drift_l2_any else "ok_or_uncompared",
        },
    )


async def query_trace(
    trace_id: str,
    *,
    log_file: Path,
    since: datetime | None = None,
    store: ConversationStore | None = None,
    jsonl_gap: dict[str, Any] | None = None,
) -> TimelineQueryResult:
    """Exact-ID query: synthetic traffic is always included; class in meta.traffic."""
    log_events, stats = load_log_events(
        trace_id,
        field="trace_id",
        log_file=log_file,
        since=since,
    )
    conv_id = extract_conversation_id(log_events)
    turn_spine: list[dict[str, Any]] = []
    if conv_id:
        turn_spine = load_conversation_spine_events(
            conv_id,
            log_file=log_file,
            since=since,
        )
    traffic = detect_traffic(log_events)
    spine = await _build_spine_for_trace(
        trace_id,
        log_events,
        store=store,
        conversation_id=conv_id,
        traffic=traffic,
        jsonl_gap=jsonl_gap,
    )
    drift_l2 = (spine.get("health") or {}).get("drift_l2") or {}
    return TimelineQueryResult(
        mode="trace",
        trace_id=trace_id,
        log_events=log_events,
        spine_events=turn_spine,
        decision_spine=spine,
        meta={
            "conversation_id": conv_id,
            "traffic": traffic,
            "bad_lines": stats.bad_lines,
            "files": [str(p) for p in stats.files],
            "drift_l2": drift_l2,
        },
    )


async def query_recent(
    n: int,
    *,
    store: ConversationStore,
) -> TimelineQueryResult:
    recent = await store.list_recent(n)
    return TimelineQueryResult(mode="recent", recent=recent, meta={"n": n})
