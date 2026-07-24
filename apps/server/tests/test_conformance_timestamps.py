"""Wall-clock timestamp scheme for conformance fixtures (卡片「用时」可读)."""

from __future__ import annotations

from agentcore.conformance.timestamps import (
    format_stable_timestamp,
    wall_clock_ms_sequence,
)


def test_parallel_runs_share_wall_clock():
    """Four parallel completes + one dependent: span ≈ max(parallel) + synth."""
    events = [
        ("message_start", {}),
        ("run_started", {"run_id": "a"}),
        ("run_started", {"run_id": "b"}),
        ("run_completed", {"run_id": "a", "duration_ms": 2000}),
        ("run_completed", {"run_id": "b", "duration_ms": 2400}),
        ("run_started", {"run_id": "c"}),
        ("run_completed", {"run_id": "c", "duration_ms": 2800}),
        ("message_end", {}),
    ]
    ms = wall_clock_ms_sequence(events)
    assert ms[-1] - ms[0] >= 2400 + 2800
    # Parallel a/b must not stack to 2000+2400 before c starts.
    assert ms[4] - ms[0] < 2000 + 2400


def test_format_stable_timestamp_millis():
    assert format_stable_timestamp(1) == "2026-01-01T00:00:00.001Z"
    assert format_stable_timestamp(1500) == "2026-01-01T00:00:01.500Z"
