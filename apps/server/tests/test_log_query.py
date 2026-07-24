"""Unit tests for the unified product-AI log query layer."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentcore.observability.query.jsonl import (
    JsonlLogSource,
    ReadFilter,
    discover_log_files,
    iter_events,
    load_events,
)
from agentcore.observability.query.stats import accumulate_trace, compute_stats, new_trace
from agentcore.observability.query.timeline import detect_traffic, query_trace
from agentcore.observability.query.timeutil import parse_since, parse_timestamp


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def test_discover_log_files_oldest_to_newest(tmp_path: Path):
    primary = tmp_path / "dev.jsonl"
    _write_jsonl(primary, [{"event": "a", "timestamp": "2026-07-01T00:00:00Z"}])
    (tmp_path / "dev.jsonl.1").write_text(
        json.dumps({"event": "b", "timestamp": "2026-06-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "dev.jsonl.2").write_text(
        json.dumps({"event": "c", "timestamp": "2026-05-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    files = discover_log_files(primary)
    assert [p.name for p in files] == ["dev.jsonl.2", "dev.jsonl.1", "dev.jsonl"]


def test_synthetic_filter_default_excludes(tmp_path: Path):
    primary = tmp_path / "dev.jsonl"
    _write_jsonl(
        primary,
        [
            {"event": "chat.turn_start", "timestamp": "2026-07-18T10:00:00Z"},
            {
                "event": "chat.turn_start",
                "timestamp": "2026-07-18T10:01:00Z",
                "traffic": "eval",
            },
            {
                "event": "chat.turn_start",
                "timestamp": "2026-07-18T10:02:00Z",
                "traffic": "test",
            },
        ],
    )
    kept, stats = load_events(primary, ReadFilter(include_synthetic=False))
    assert len(kept) == 1
    assert stats.excluded_synthetic == 2
    assert stats.synthetic_by_kind == {"eval": 1, "test": 1}

    kept_all, stats_all = load_events(primary, ReadFilter(include_synthetic=True))
    assert len(kept_all) == 3
    assert stats_all.excluded_synthetic == 0


def test_since_filter(tmp_path: Path):
    primary = tmp_path / "dev.jsonl"
    _write_jsonl(
        primary,
        [
            {"event": "old", "timestamp": "2026-07-01T00:00:00Z"},
            {"event": "new", "timestamp": "2026-07-18T12:00:00Z"},
        ],
    )
    since = datetime(2026, 7, 10, tzinfo=UTC)
    events = list(
        iter_events(JsonlLogSource(primary), ReadFilter(since=since, include_synthetic=True))
    )
    assert [e["event"] for e in events] == ["new"]


def test_parse_since_relative():
    now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    assert parse_since("24h", now=now) == now - timedelta(hours=24)
    assert parse_since("7d", now=now) == now - timedelta(days=7)


def test_parse_timestamp_z():
    dt = parse_timestamp("2026-07-18T08:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


@pytest.mark.asyncio
async def test_exact_trace_query_includes_synthetic_and_annotates(tmp_path: Path):
    # A trace belongs entirely to one traffic class — exact-ID queries must not
    # filter it away; the class surfaces in meta.traffic instead.
    primary = tmp_path / "dev.jsonl"
    _write_jsonl(
        primary,
        [
            {
                "event": "chat.turn_start",
                "timestamp": "2026-07-18T10:00:00Z",
                "trace_id": "evaltrace",
                "conversation_id": "conv-1",
                "traffic": "eval",
            },
            {
                "event": "chat.turn_complete",
                "timestamp": "2026-07-18T10:00:05Z",
                "trace_id": "evaltrace",
                "conversation_id": "conv-1",
                "traffic": "eval",
            },
            {
                "event": "chat.turn_start",
                "timestamp": "2026-07-18T11:00:00Z",
                "trace_id": "realtrace",
                "conversation_id": "conv-2",
            },
        ],
    )
    result = await query_trace("evaltrace", log_file=primary)
    assert len(result.log_events) == 2  # NOT filtered away
    assert result.meta["traffic"] == "eval"
    payload = json.loads(json.dumps(result.to_json_dict(), default=str))
    assert payload["meta"]["traffic"] == "eval"

    real = await query_trace("realtrace", log_file=primary)
    assert len(real.log_events) == 1
    assert real.meta["traffic"] is None


def test_detect_traffic():
    assert detect_traffic([{"event": "x"}, {"event": "y", "traffic": "test"}]) == "test"
    assert detect_traffic([{"event": "x"}]) is None


def test_compute_stats_json_serializable(tmp_path: Path):
    primary = tmp_path / "dev.jsonl"
    _write_jsonl(
        primary,
        [
            {
                "event": "chat.turn_complete",
                "timestamp": "2026-07-18T10:00:00Z",
                "trace_id": "abc",
                "delegated": True,
                "duration_ms": 100,
                "rounds": 2,
                "input_tokens": 10,
                "output_tokens": 20,
            },
            {
                "event": "tool.execute_end",
                "timestamp": "2026-07-18T10:00:01Z",
                "trace_id": "abc",
                "tool": "web_search",
                "status": "ok",
                "duration_ms": 5,
            },
            {
                "event": "chat.turn_start",
                "timestamp": "2026-07-18T10:00:02Z",
                "traffic": "eval",
            },
        ],
    )
    result = compute_stats(primary, include_synthetic=False, window_label="test")
    payload = result.to_json_dict()
    # Must be json.loads-roundtrippable
    again = json.loads(json.dumps(payload, default=str))
    assert again["total"] == 2
    assert again["excluded_synthetic"] == 1
    assert again["event_counts"]["chat.turn_complete"] == 1


def test_accumulate_trace_folds_collab_signals():
    rec = new_trace()
    accumulate_trace(rec, "chat.turn_complete", {"delegated": True, "finish_reason": "end_turn"})
    accumulate_trace(rec, "delegate.started", {})
    accumulate_trace(rec, "engine.loop_nudge", {})
    assert rec["turn"] is True
    assert rec["delegated"] is True
    assert rec["loop_nudge"] == 1
