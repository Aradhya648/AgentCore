"""Tests for decision_spine contract (default product-AI log evidence surface)."""

from __future__ import annotations

from agentcore.observability.query.decision_spine import (
    SCHEMA_VERSION,
    build_decision_spine,
    compute_drift_l2,
    format_decision_spine,
)
from agentcore.observability.query.timeline import TimelineQueryResult


def _events_delegated_ok(trace_id: str = "a" * 32) -> list[dict]:
    return [
        {
            "type": "log",
            "event": "chat.turn_start",
            "timestamp": "2026-07-31T10:00:00Z",
            "trace_id": trace_id,
            "conversation_id": "conv-1",
            "preview": "请委派写报告",
            "chars": 12,
            "history": 0,
        },
        {
            "type": "log",
            "event": "delegate.started",
            "timestamp": "2026-07-31T10:00:01Z",
            "trace_id": trace_id,
            "agents": ["writer"],
            "nodes": 1,
            "plan": [{"id": "n1", "role": "writer", "depends_on": []}],
            "waves": [["n1"]],
        },
        {
            "type": "log",
            "event": "delegate.completion_criteria_unmet",
            "timestamp": "2026-07-31T10:00:05Z",
            "trace_id": trace_id,
            "criteria": "code_verified",
            "gaps": ["missing_tests"],
            "execution_id": "ex1",
            "escalate": True,
        },
        {
            "type": "log",
            "event": "llm.call",
            "timestamp": "2026-07-31T10:00:06Z",
            "trace_id": trace_id,
            "model": "demo",
            "input_tokens": 10,
            "output_tokens": 20,
            "cost_nano": 100,
        },
        {
            "type": "log",
            "event": "chat.turn_complete",
            "timestamp": "2026-07-31T10:00:10Z",
            "trace_id": trace_id,
            "finish_reason": "stop",
            "delegated": True,
            "workers": 1,
            "rounds": 2,
            "duration_ms": 10000,
            "input_tokens": 10,
            "output_tokens": 20,
            "boundary_yields": 0,
            "scope_signals": 0,
            "revises": 0,
            "escalations": 0,
            "reply_preview": "done",
        },
    ]


def test_build_decision_spine_covers_key_decisions() -> None:
    spine = build_decision_spine(_events_delegated_ok(), trace_id="a" * 32)
    assert spine["schema_version"] == SCHEMA_VERSION
    assert spine["trace_id"] == "a" * 32
    assert spine["conversation_id"] == "conv-1"
    assert "委派" in (spine["head"].get("preview") or "") or spine["head"]["preview"]
    events = {d["event"] for d in spine["decisions"]}
    assert "delegate.started" in events
    assert "delegate.completion_criteria_unmet" in events
    assert spine["llm"]["calls"] == 1
    assert spine["tail"]["source"] == "jsonl_close"
    assert spine["tail"]["finish_reason"] == "stop"
    assert spine["tail"]["delegated"] is True
    assert spine["health"]["drift_l2"]["reason"] == "turn_metrics_missing"


def test_tail_prefers_turn_metrics_and_l2_aligned() -> None:
    tid = "b" * 32
    events = _events_delegated_ok(tid)
    metrics = {
        "trace_id": tid,
        "status": "ok",
        "finish_reason": "stop",
        "delegated": True,
        "workers": 1,
        "rounds": 2,
        "duration_ms": 10000,
        "input_tokens": 10,
        "output_tokens": 20,
        "boundary_yields": 0,
        "scope_signals": 0,
        "revises": 0,
        "escalations": 0,
        "kind": "turn",
        "turn_id": "t1",
    }
    spine = build_decision_spine(events, turn_metrics=metrics, cost_events={"total_nano": 42})
    assert spine["tail"]["source"] == "turn_metrics"
    assert spine["tail"]["finish_reason"] == "stop"
    assert spine["tail"]["delegated"] is True
    assert spine["cost"]["source"] == "cost_events"
    assert spine["cost"]["total_nano"] == 42
    assert spine["health"]["drift_l2"]["ok"] is True
    assert spine["health"]["drift_l2"]["compared"] is True


def test_drift_l2_marks_mismatch() -> None:
    tid = "c" * 32
    events = _events_delegated_ok(tid)
    metrics = {
        "trace_id": tid,
        "finish_reason": "stop",
        "delegated": True,
        "workers": 1,
        "rounds": 2,
        "input_tokens": 10,
        "output_tokens": 20,
        "boundary_yields": 0,
        "scope_signals": 0,
        "revises": 0,
        "escalations": 9,  # diverge from JSONL close (=0)
    }
    drift = compute_drift_l2(
        turn_metrics=metrics,
        close=events[-1],
        recomputed={"escalations": 0, "yields": 0, "scope_boundaries": 0, "revise": 0},
    )
    assert drift["ok"] is False
    assert any(m["field"] == "escalations" for m in drift["mismatches"])
    spine = build_decision_spine(events, turn_metrics=metrics)
    text = format_decision_spine(spine)
    assert "Drift L2" in text
    assert "escalations" in text


def test_timeline_json_default_is_decision_spine_not_firehose() -> None:
    spine = build_decision_spine(_events_delegated_ok())
    result = TimelineQueryResult(
        mode="trace",
        trace_id="a" * 32,
        log_events=[{"event": "noise"}] * 5,
        decision_spine=spine,
        meta={"traffic": None},
    )
    payload = result.to_json_dict(raw=False)
    assert "decision_spine" in payload
    assert "log_events" not in payload
    assert payload["decision_spine"]["schema_version"] == SCHEMA_VERSION
    raw_payload = result.to_json_dict(raw=True)
    assert "log_events" in raw_payload
    assert len(raw_payload["log_events"]) == 5


def test_format_decision_spine_readable() -> None:
    text = format_decision_spine(build_decision_spine(_events_delegated_ok()))
    assert "Decision Spine" in text
    assert "delegate.started" in text
    assert "delegate.completion_criteria_unmet" in text
    assert "finish=stop" in text
