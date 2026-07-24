"""Pacing helpers for demo tape playback."""

from __future__ import annotations


def pacing_step(
    *,
    prev_t_ms: int | None,
    t_ms: int,
) -> tuple[int, int]:
    """Compute inter-event gap and the next pacing clock.

    Returns ``(gap_ms, new_prev_t_ms)``.

    - First event (``prev_t_ms is None``): no sleep; clock becomes ``t_ms``.
    - Time going backwards / equal: gap 0; clock **does not rewind** (keeps
      ``max(prev, t)``). Rewinding would re-sleep wall time already spent on
      synthetic chunk overshoot and create multi-minute false silences once
      ``max_gap_ms`` no longer masks them.
    """
    if prev_t_ms is None:
        return 0, int(t_ms)
    prev = int(prev_t_ms)
    cur = int(t_ms)
    gap = cur - prev
    return (gap if gap > 0 else 0), max(prev, cur)


def sleep_ms_for_gap(
    *,
    gap_ms: int,
    speed: float,
    max_gap_ms: int,
) -> float:
    """Return sleep seconds for an original inter-event gap under speed / cap.

    ``gap_ms`` is the wall-clock gap on the source tape (``t_ms[i] - t_ms[i-1]``).
    Negative / zero gaps → no sleep. ``speed`` > 1 shortens waits; ``max_gap_ms``
    caps long idle stretches (tool waits, LLM think time) so demos stay watchable.
    """
    if gap_ms <= 0:
        return 0.0
    speed = max(float(speed), 0.1)
    capped = min(int(gap_ms), int(max_gap_ms))
    return (capped / speed) / 1000.0
