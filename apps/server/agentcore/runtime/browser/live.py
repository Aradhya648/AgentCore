"""BrowserLiveHub — per-conversation live screencast fan-out (M1 · D13).

The live-frame bypass (D13) mirrors the sim tick-frame precedent's SHAPE (an independent
per-conversation live registry + an attach-style SSE) but is purpose-built for a high-rate
screencast:

- **viewer-driven lifecycle**: screencast starts on the FIRST viewer attach and stops when the
  LAST viewer leaves (after a short grace so a refresh does not thrash). No viewers ⇒ zero
  screencast cost. A watched session is spared idle-TTL reaping via the registry observer
  (``is_watched``); ``max_lifetime`` still recycles it.
- **fan-out with backpressure**: one driver produces frames; the hub broadcasts each to every
  viewer's OWN bounded queue that drops the oldest on overflow (latest-frame-wins) so a slow /
  stalled viewer can never grow memory or add latency.
- **status honesty**: a viewer with no live session gets ``no_session``; a session appearing
  later flips it to ``started``; a watched session recycled/closed emits ``session_closed``.

All events are EPHEMERAL (``browser_live_frame`` / ``browser_live_status``) and never touch the
turn journal — they ride standalone per-viewer queues, drained by the SSE endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.runtime.events import SSEEvent, browser_live_frame, browser_live_status
from agentcore.tools.sandbox.browser.protocol import BrowserDriverCrashedError, BrowserSession

logger = get_logger(__name__)

# Peek the conversation's live session WITHOUT creating one (registry.peek); None ⇒ no session.
SessionLookup = Callable[[str], BrowserSession | None]


class BrowserLiveViewer:
    """One SSE viewer's bounded frame queue: drop-oldest keeps latency low + memory bounded."""

    def __init__(self, *, max_queue: int) -> None:
        self._queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=max(1, max_queue))
        self._closed = False

    def emit(self, event: SSEEvent) -> None:
        """Enqueue an event; when full, drop the OLDEST so the newest frame/status wins."""
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(event)

    async def get(self) -> SSEEvent | None:
        """Next event, or None once closed (stream sentinel)."""
        return await self._queue.get()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(None)


@dataclass
class _LiveChannel:
    conversation_id: str
    viewers: set[BrowserLiveViewer] = field(default_factory=set)
    screencast_on: bool = False
    stop_timer: asyncio.TimerHandle | None = None


class BrowserLiveHub:
    """Process-wide ``conversation_id → live channel`` fan-out + registry observer (D13)."""

    def __init__(
        self,
        *,
        session_lookup: SessionLookup,
        grace_seconds: float | None = None,
        max_queued_frames: int | None = None,
    ) -> None:
        self._lookup = session_lookup
        self._grace = grace_seconds
        self._max_q = max_queued_frames
        self._channels: dict[str, _LiveChannel] = {}
        self._lock = asyncio.Lock()
        # Fire-and-forget detach tasks (scheduled from the SSE generator's finally, where an
        # await would race the request cancellation) — referenced so they aren't GC'd.
        self._pending_detach: set[asyncio.Task] = set()

    @property
    def grace_seconds(self) -> float:
        if self._grace is not None:
            return self._grace
        return float(settings.browser_live_grace_seconds)

    @property
    def max_queued_frames(self) -> int:
        if self._max_q is not None:
            return self._max_q
        return int(settings.browser_live_max_queued_frames)

    # -- viewer lifecycle ------------------------------------------------------
    async def attach(self, conversation_id: str) -> BrowserLiveViewer:
        """Register a viewer; start screencast if it's the first + a session exists."""
        async with self._lock:
            channel = self._channels.get(conversation_id)
            if channel is None:
                channel = _LiveChannel(conversation_id=conversation_id)
                self._channels[conversation_id] = channel
            self._cancel_stop_timer(channel)
            viewer = BrowserLiveViewer(max_queue=self.max_queued_frames)
            channel.viewers.add(viewer)
            session = self._lookup(conversation_id)
            if session is not None and session.alive:
                if not channel.screencast_on:
                    await self._begin_screencast(channel, session)
                if channel.screencast_on:
                    viewer.emit(browser_live_status("started"))
            else:
                viewer.emit(browser_live_status("no_session"))
            logger.info(
                "browser.live_attached",
                conversation_id=conversation_id,
                viewers=len(channel.viewers),
            )
            return viewer

    def detach_soon(self, conversation_id: str, viewer: BrowserLiveViewer) -> None:
        """Schedule :meth:`detach` as an independent task (safe from the SSE finally).

        The SSE generator's cleanup runs while the request is being cancelled, so awaiting
        there could be interrupted mid-detach and leak a viewer (⇒ screencast never stops).
        Creating the task is synchronous and immune to that; a held reference keeps it alive.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            viewer.close()
            return
        task = loop.create_task(self.detach(conversation_id, viewer))
        self._pending_detach.add(task)
        task.add_done_callback(self._pending_detach.discard)

    async def detach(self, conversation_id: str, viewer: BrowserLiveViewer) -> None:
        """Drop a viewer; schedule a grace-period screencast stop if it was the last."""
        async with self._lock:
            channel = self._channels.get(conversation_id)
            if channel is None:
                viewer.close()
                return
            channel.viewers.discard(viewer)
            viewer.close()
            logger.info(
                "browser.live_detached",
                conversation_id=conversation_id,
                viewers=len(channel.viewers),
            )
            if not channel.viewers:
                self._schedule_stop(channel)

    # -- registry observer (sync, non-blocking) --------------------------------
    def on_session_ready(self, conversation_id: str) -> None:
        self._schedule(self._react_ready(conversation_id))

    def on_session_gone(self, conversation_id: str) -> None:
        self._schedule(self._react_gone(conversation_id))

    def is_watched(self, conversation_id: str) -> bool:
        channel = self._channels.get(conversation_id)
        return bool(channel and channel.viewers)

    # -- internal --------------------------------------------------------------
    async def _react_ready(self, conversation_id: str) -> None:
        async with self._lock:
            channel = self._channels.get(conversation_id)
            if channel is None or not channel.viewers or channel.screencast_on:
                return
            session = self._lookup(conversation_id)
            if session is None or not session.alive:
                return
            await self._begin_screencast(channel, session)
            if channel.screencast_on:
                self._broadcast(channel, browser_live_status("started"))

    async def _react_gone(self, conversation_id: str) -> None:
        async with self._lock:
            channel = self._channels.get(conversation_id)
            if channel is None:
                return
            was_on = channel.screencast_on
            channel.screencast_on = False
            self._cancel_stop_timer(channel)
            if channel.viewers:
                self._broadcast(channel, browser_live_status("session_closed"))
            elif not was_on:
                # No viewers and nothing running — drop the empty channel.
                self._channels.pop(conversation_id, None)

    async def _begin_screencast(self, channel: _LiveChannel, session: BrowserSession) -> None:
        session.set_frame_listener(self._make_frame_sink(channel))
        try:
            await session.start_screencast()
        except BrowserDriverCrashedError:
            session.set_frame_listener(None)
            self._broadcast(channel, browser_live_status("session_closed"))
            logger.warning(
                "browser.screencast_start_failed", conversation_id=channel.conversation_id
            )
            return
        channel.screencast_on = True
        logger.info("browser.screencast_started", conversation_id=channel.conversation_id)

    def _make_frame_sink(self, channel: _LiveChannel) -> Callable[[dict[str, Any]], None]:
        def sink(frame: dict[str, Any]) -> None:
            self._broadcast(
                channel,
                browser_live_frame(
                    frame_b64=str(frame.get("frame_b64") or ""),
                    width=int(frame.get("width") or 0),
                    height=int(frame.get("height") or 0),
                ),
            )

        return sink

    def _broadcast(self, channel: _LiveChannel, event: SSEEvent) -> None:
        for viewer in list(channel.viewers):
            viewer.emit(event)

    def _schedule_stop(self, channel: _LiveChannel) -> None:
        self._cancel_stop_timer(channel)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        cid = channel.conversation_id
        channel.stop_timer = loop.call_later(
            self.grace_seconds, lambda: self._schedule(self._grace_stop(cid))
        )

    async def _grace_stop(self, conversation_id: str) -> None:
        async with self._lock:
            channel = self._channels.get(conversation_id)
            if channel is None or channel.viewers:
                return  # a viewer re-attached within the grace window
            channel.stop_timer = None
            if channel.screencast_on:
                session = self._lookup(conversation_id)
                if session is not None:
                    session.set_frame_listener(None)
                    with contextlib.suppress(Exception):
                        await session.stop_screencast()
                channel.screencast_on = False
                logger.info(
                    "browser.screencast_stopped", conversation_id=conversation_id
                )
            self._channels.pop(conversation_id, None)

    def _cancel_stop_timer(self, channel: _LiveChannel) -> None:
        if channel.stop_timer is not None:
            channel.stop_timer.cancel()
            channel.stop_timer = None

    def _schedule(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()


_hub: BrowserLiveHub | None = None


def default_browser_live_hub() -> BrowserLiveHub:
    """The process-wide live hub, wired to the default registry (observer + session peek)."""
    global _hub
    if _hub is None:
        from agentcore.runtime.browser.registry import default_browser_session_registry

        registry = default_browser_session_registry()
        _hub = BrowserLiveHub(session_lookup=registry.peek)
        registry.set_observer(_hub)
    return _hub
