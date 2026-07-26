"""Turn-level Phase-0 latency probe (observation only — no product behavior change).

Four fields on ``chat.turn_complete``:

- ``prepare_ms`` / ``assemble_ms`` — wall-clock duration of the existing
  ``prepare_fresh_turn`` / ``assemble_ceo_turn`` calls (not LLM latency).
- ``ttft_reasoning_ms`` / ``ttft_content_ms`` — elapsed ms from the turn anchor
  (monotonic fixed early at user-message handling) to the **first** CEO/captain
  LLM stream's first reasoning chunk / first content-or-tool chunk (whichever of
  content delta vs tool_call delta arrives first for content).

Missing paths stay ``None`` (JSON null) — never a fake ``0``. Subsequent captain
rounds and all worker streams do not overwrite the TTFT pair.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class TurnLatencyProbe:
    """Mutable accumulator for one turn attempt's Phase-0 latency fields."""

    anchor_mono: float
    prepare_ms: int | None = None
    assemble_ms: int | None = None
    ttft_reasoning_ms: int | None = None
    ttft_content_ms: int | None = None
    _captain_stream_armed: bool = False
    _captain_first_stream_done: bool = False
    _recording_this_stream: bool = False

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.anchor_mono) * 1000)

    def mark_prepare(self, wall_ms: int) -> None:
        """Record prepare wall-clock once (first call wins)."""
        if self.prepare_ms is None:
            self.prepare_ms = wall_ms

    def mark_assemble(self, wall_ms: int) -> None:
        """Record assemble wall-clock once (first call wins)."""
        if self.assemble_ms is None:
            self.assemble_ms = wall_ms

    def begin_captain_stream(self) -> bool:
        """Arm TTFT recording for the first captain stream only.

        Returns True when this stream should note first chunks.
        """
        if self._captain_first_stream_done or self._captain_stream_armed:
            return False
        self._captain_stream_armed = True
        self._recording_this_stream = True
        return True

    def end_captain_stream(self) -> None:
        """Close the armed first-stream window (idempotent)."""
        if not self._recording_this_stream and not self._captain_stream_armed:
            return
        self._recording_this_stream = False
        self._captain_stream_armed = False
        self._captain_first_stream_done = True

    def clear_ttft(self) -> None:
        """Drop in-flight TTFT marks (stream_reset / pre-commit stall retry)."""
        if not self._recording_this_stream:
            return
        self.ttft_reasoning_ms = None
        self.ttft_content_ms = None

    def note_reasoning_chunk(self) -> None:
        if self._recording_this_stream and self.ttft_reasoning_ms is None:
            self.ttft_reasoning_ms = self.elapsed_ms()

    def note_content_or_tool_chunk(self) -> None:
        if self._recording_this_stream and self.ttft_content_ms is None:
            self.ttft_content_ms = self.elapsed_ms()

    def as_log_fields(self) -> dict[str, int | None]:
        """Always emit the four keys; absent paths are ``None`` (not ``0``)."""
        return {
            "prepare_ms": self.prepare_ms,
            "assemble_ms": self.assemble_ms,
            "ttft_reasoning_ms": self.ttft_reasoning_ms,
            "ttft_content_ms": self.ttft_content_ms,
        }


current_turn_latency: ContextVar[TurnLatencyProbe | None] = ContextVar(
    "current_turn_latency", default=None
)


def bind_turn_latency(anchor_mono: float | None = None) -> tuple[TurnLatencyProbe, Token]:
    """Install a fresh probe for this turn attempt; caller must ``reset`` the token."""
    probe = TurnLatencyProbe(anchor_mono=time.monotonic() if anchor_mono is None else anchor_mono)
    return probe, current_turn_latency.set(probe)


def get_turn_latency() -> TurnLatencyProbe | None:
    return current_turn_latency.get()


def reset_turn_latency(token: Token) -> None:
    current_turn_latency.reset(token)
