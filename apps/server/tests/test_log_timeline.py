"""Tests for log_timeline jsonl gap → journal hint."""

from __future__ import annotations

from scripts.log_timeline import (
    detect_jsonl_timeline_gap,
    format_timeline,
    format_trace,
)


def test_detect_gap_on_timestamp_hole() -> None:
    events = [
        {"event": "chat.turn_start", "timestamp": "2026-07-22T10:00:00Z", "type": "log"},
        {"event": "react.round_end", "timestamp": "2026-07-22T10:05:00Z", "type": "log"},
    ]
    gap = detect_jsonl_timeline_gap(events, min_gap_seconds=120)
    assert gap is not None
    assert gap["reason"] == "timestamp_gap"
    assert gap["gap_seconds"] == 300.0


def test_detect_gap_on_rollover_failed_event() -> None:
    events = [
        {
            "event": "logging.rollover_failed",
            "timestamp": "2026-07-22T10:00:00Z",
            "type": "log",
        },
        {"event": "chat.turn_start", "timestamp": "2026-07-22T10:00:01Z", "type": "log"},
    ]
    gap = detect_jsonl_timeline_gap(events)
    assert gap is not None
    assert gap["reason"] == "rollover_failed"


def test_no_gap_for_dense_timeline() -> None:
    events = [
        {"event": "a", "timestamp": "2026-07-22T10:00:00Z", "type": "log"},
        {"event": "b", "timestamp": "2026-07-22T10:00:30Z", "type": "log"},
    ]
    assert detect_jsonl_timeline_gap(events, min_gap_seconds=120) is None


def test_format_trace_includes_journal_hint() -> None:
    events = [
        {"event": "chat.turn_start", "timestamp": "2026-07-22T10:00:00Z", "type": "log"},
        {"event": "chat.turn_complete", "timestamp": "2026-07-22T10:10:00Z", "type": "log"},
    ]
    out = format_trace("abc", events)
    assert "以 Postgres journal 为准" in out
    assert "gap≈600s" in out


def test_format_timeline_includes_journal_hint_on_rollover() -> None:
    events = [
        {
            "event": "logging.rollover_failed",
            "timestamp": "2026-07-22T10:00:00Z",
            "type": "log",
        },
    ]
    out = format_timeline(
        {"id": "c1", "title": "t", "agent_id": "a", "created_at": "2026-07-22"},
        [],
        events,
    )
    assert "以 Postgres journal 为准" in out
