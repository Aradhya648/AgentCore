"""Deterministic wall-clock timestamps for conformance fixtures.

Projection ignores timestamps, but desktop ``elapsedMs`` (card 「用时」) is
``last_frame.t − first_frame.t``. A 1ms-per-event scheme collapses every turn
to 「用时 0s``. This module advances a simulated clock from ``run_completed``
``duration_ms`` so parallel waves don't overcount (same wall-clock semantics
as the frontend).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def format_stable_timestamp(ms: int) -> str:
    """Format simulated ms-since-base as an ISO-8601 UTC stamp with millis."""
    dt = _BASE + timedelta(milliseconds=ms)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_clock_ms_sequence(
    events: Sequence[tuple[str, Any]],
) -> list[int]:
    """Return one monotonic ms offset per event.

    Rules:
    - +1ms per event (stable ordering / byte-identical re-export)
    - on ``run_completed`` with ``duration_ms``: jump to
      ``max(clock, run_start + duration)`` so concurrent runs share wall time
    """
    clock_ms = 0
    run_starts: dict[str, int] = {}
    out: list[int] = []
    for typ, payload in events:
        clock_ms += 1
        p: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
        if typ == "run_started":
            rid = p.get("run_id")
            if isinstance(rid, str) and rid:
                run_starts[rid] = clock_ms
        elif typ == "run_completed":
            rid = p.get("run_id")
            dur = p.get("duration_ms")
            if isinstance(rid, str) and isinstance(dur, int) and dur > 0:
                start = run_starts.get(rid, clock_ms)
                clock_ms = max(clock_ms, start + dur)
        out.append(clock_ms)
    return out
