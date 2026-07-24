"""Live playback transport for demo-tape director control (dev-only).

The player loop consults a per-conversation :class:`PlaybackTransport` for
pause / speed / burst-seek. REST handlers mutate the same object so mid-play
speed changes take effect on the next sleep slice without jumping events.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class PlaybackState(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"  # director soft-pause (metronome held)
    AWAITING_INTERACTION = "awaiting_interaction"  # cold durable card or hot approval
    SEEKING = "seeking"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class PlaybackTransport:
    """Mutable metronome shared by the player loop and director REST."""

    conversation_id: str
    tape_path: Path
    speed: float
    max_gap_ms: int
    event_count: int = 0
    duration_ms: int = 0
    tape_id: str = ""

    state: PlaybackState = PlaybackState.IDLE
    event_index: int = 0
    t_ms: int = 0
    message_id: str | None = None

    # Burst-seek: skip inter-event delays for indices ``< burst_until_index``.
    burst_until_index: int | None = None
    # When True, durable pause cards crossed during burst are auto-resolved.
    auto_resolve_pauses: bool = False

    error: str | None = None
    updated_at: float = field(default_factory=time.monotonic)

    _paused: bool = field(default=False, repr=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def touch(self) -> None:
        self.updated_at = time.monotonic()

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.5, min(float(speed), 8.0))
        self.touch()
        self._wake.set()

    def pause(self) -> None:
        if self.state in (PlaybackState.FINISHED, PlaybackState.ERROR):
            return
        self._paused = True
        if self.state == PlaybackState.PLAYING:
            self.state = PlaybackState.PAUSED
        self.touch()
        self._wake.set()

    def resume(self) -> None:
        self._paused = False
        if self.state == PlaybackState.PAUSED:
            self.state = PlaybackState.PLAYING
        self.touch()
        self._wake.set()

    def is_soft_paused(self) -> bool:
        return self._paused

    def begin_play(self, *, message_id: str, start_index: int = 0) -> None:
        self.message_id = message_id
        self.event_index = start_index
        self.state = PlaybackState.PAUSED if self._paused else PlaybackState.PLAYING
        self.error = None
        self.touch()

    def mark_awaiting_interaction(self, *, event_index: int, t_ms: int) -> None:
        self.event_index = event_index
        self.t_ms = t_ms
        self.state = PlaybackState.AWAITING_INTERACTION
        self.touch()

    def clear_awaiting_interaction(self) -> None:
        """Leave hot-path wait and resume metronome state (soft-pause preserved)."""
        if self.state != PlaybackState.AWAITING_INTERACTION:
            return
        self.state = PlaybackState.PAUSED if self._paused else PlaybackState.PLAYING
        self.touch()

    def mark_finished(self) -> None:
        self.state = PlaybackState.FINISHED
        self.burst_until_index = None
        self.auto_resolve_pauses = False
        self.touch()

    def mark_error(self, message: str) -> None:
        self.state = PlaybackState.ERROR
        self.error = message
        self.touch()

    def report_position(self, *, event_index: int, t_ms: int) -> None:
        self.event_index = event_index
        self.t_ms = int(t_ms)
        self.touch()

    def arm_burst(self, until_index: int, *, auto_resolve: bool) -> None:
        self.burst_until_index = max(0, int(until_index))
        self.auto_resolve_pauses = bool(auto_resolve)
        self.state = PlaybackState.SEEKING
        self.touch()
        self._wake.set()

    def clear_burst_if_reached(self, event_index: int) -> None:
        if self.burst_until_index is None:
            return
        if event_index >= self.burst_until_index:
            self.burst_until_index = None
            self.auto_resolve_pauses = False
            if self.state == PlaybackState.SEEKING:
                self.state = PlaybackState.PAUSED if self._paused else PlaybackState.PLAYING
            self.touch()

    def should_skip_delay(self, event_index: int) -> bool:
        return (
            self.burst_until_index is not None and event_index < self.burst_until_index
        )

    def should_auto_resolve_at(self, event_index: int) -> bool:
        """True when seek target is *past* this interactive event (cross it)."""
        if not self.auto_resolve_pauses:
            return False
        if self.burst_until_index is None:
            return False
        return event_index < self.burst_until_index

    async def await_gap(self, gap_ms: int, *, event_index: int) -> None:
        """Sleep for a tape gap under live speed / pause / burst.

        Interruptible: speed changes, pause/resume, and burst arming wake the
        waiter. Remaining time is tracked in tape-ms so a mid-wait speed change
        applies to the leftover gap (no event jump).

        Sub-millisecond wall slices are skipped: on Windows,
        ``asyncio.wait_for`` timer resolution often costs 1–15ms per call, so
        long tapes with high ``speed`` / small ``max_gap_ms`` would otherwise
        burn tens of seconds in timer overhead (and hydrate tests time out).
        """
        if self.should_skip_delay(event_index):
            return
        if gap_ms <= 0:
            return

        remaining_tape_ms = float(min(int(gap_ms), int(self.max_gap_ms)))
        while remaining_tape_ms > 0:
            if self.should_skip_delay(event_index):
                return
            while self._paused:
                self._wake.clear()
                await self._wake.wait()
                if self.should_skip_delay(event_index):
                    return
            speed = max(float(self.speed), 0.1)
            # ~50ms wall slices; tape slice scales with speed.
            slice_tape_ms = min(remaining_tape_ms, 50.0 * speed)
            wall_s = (slice_tape_ms / speed) / 1000.0
            if wall_s < 0.001:
                remaining_tape_ms -= slice_tape_ms
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wall_s)
                # Woken early (speed/pause/seek) — re-loop with remaining tape ms.
            except TimeoutError:
                remaining_tape_ms -= slice_tape_ms

    def snapshot(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "tape_id": self.tape_id,
            "tape_path": str(self.tape_path),
            "state": self.state.value,
            "speed": self.speed,
            "max_gap_ms": self.max_gap_ms,
            "event_index": self.event_index,
            "event_count": self.event_count,
            "t_ms": self.t_ms,
            "duration_ms": self.duration_ms,
            "message_id": self.message_id,
            "burst_until_index": self.burst_until_index,
            "soft_paused": self._paused,
            "error": self.error,
        }


class TransportRegistry:
    """Process-local registry of live director transports."""

    def __init__(self) -> None:
        self._by_conversation: dict[str, PlaybackTransport] = {}

    def get(self, conversation_id: str) -> PlaybackTransport | None:
        return self._by_conversation.get(conversation_id)

    def list_active(self) -> list[PlaybackTransport]:
        return list(self._by_conversation.values())

    def attach(
        self,
        *,
        conversation_id: str,
        tape_path: Path,
        speed: float,
        max_gap_ms: int,
        event_count: int,
        duration_ms: int,
        tape_id: str = "",
    ) -> PlaybackTransport:
        existing = self._by_conversation.get(conversation_id)
        if existing is not None and existing.state not in (
            PlaybackState.FINISHED,
            PlaybackState.ERROR,
            PlaybackState.IDLE,
        ):
            # Resume / continue: keep live speed / pause / burst arms.
            existing.tape_path = tape_path
            existing.event_count = event_count
            existing.duration_ms = duration_ms
            existing.max_gap_ms = max_gap_ms
            if tape_id:
                existing.tape_id = tape_id
            existing.touch()
            return existing

        # Preserve TapeBinding speed (tests / launch may use >>8×). Director
        # REST still clamps via ``set_speed`` (UI max 8×).
        transport = PlaybackTransport(
            conversation_id=conversation_id,
            tape_path=tape_path,
            speed=max(0.1, float(speed)) if speed else 1.0,
            max_gap_ms=int(max_gap_ms),
            event_count=event_count,
            duration_ms=duration_ms,
            tape_id=tape_id or tape_path.stem,
        )
        # Preserve director soft-pause / speed if re-attaching after finish.
        if existing is not None:
            transport.speed = existing.speed
            transport._paused = existing._paused
            if existing.burst_until_index is not None:
                transport.burst_until_index = existing.burst_until_index
                transport.auto_resolve_pauses = existing.auto_resolve_pauses
        self._by_conversation[conversation_id] = transport
        return transport

    def discard(self, conversation_id: str) -> None:
        self._by_conversation.pop(conversation_id, None)


# Module singleton (single-worker dev posture, same as turn_runs).
transport_registry = TransportRegistry()
