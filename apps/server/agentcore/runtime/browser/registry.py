"""BrowserSessionRegistry — conversation → long-lived browser session (M0 生命周期).

Mirrors ``runtime/sessions.py`` (conversation-scoped, process-wide singleton) but
for the heavy L3 browser sandboxes, with the extra guarantees the proposal pins:

- **lazy create**: a session is opened on the FIRST ``browser_*`` call, not before;
- **idle TTL** (default 10min) and **max lifetime** (default 2h): a stale/aged
  session is recycled (lazily on access + by the lifespan reaper loop);
- **concurrency gate** (``browser_max_sessions``): a new conversation past the cap
  fails fast with an explainable busy result AFTER an idle reap;
- **crash → rebuild**: a dead driver is dropped so the next call rebuilds a fresh
  sandbox (the tool tells the AI its page state was lost);
- **cascade cleanup**: closing / deleting a conversation tears the session down.

Session creation is injected as a ``factory`` so the whole lifecycle is unit-testable
with fakes (no gVisor); the default factory goes through the sandbox provider's
session surface (``SandboxProvider.open_browser_session``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.runtime.browser.keyframes import KeyframeTracker
from agentcore.tools.sandbox.browser.protocol import (
    BrowserSession,
    BrowserSessionRequest,
    BrowserSessionsBusyError,
)

logger = get_logger(__name__)

SessionFactory = Callable[[BrowserSessionRequest], Awaitable[BrowserSession]]


@dataclass(frozen=True)
class TakeoverMark:
    """The active user-takeover pinned onto a session entry (M2 · D16/D17).

    The registry entry is the single in-memory source of truth for「is this session under
    user takeover」— the tools consult it (busy error) and every teardown path uses it to
    finalize the durable record. ``record_id`` links to the ``browser_takeovers`` row so a
    drop can close it; ``started_at`` lets the endpoint reconstruct state on already-active.
    """

    record_id: str
    user_id: str
    started_at: datetime


# Called on every session teardown that still carries an un-ended takeover (reap / crash /
# shutdown / delete) so the durable record is completed on ALL paths (D17). Injected so the
# registry stays DB-agnostic and unit-testable; awaited inside ``_drop``.
TakeoverFinalizer = Callable[[TakeoverMark, str], Awaitable[None]]


class BrowserSessionObserver(Protocol):
    """Live-hub hooks the registry fires on session lifecycle (M1 · D13).

    Declared here (the registry is the caller) so the live hub implements it structurally
    without the registry importing the live module — and tests inject a fake. Callbacks MUST
    be sync + non-blocking (the hub only schedules work): they run inside registry ops.
    """

    def on_session_ready(self, conversation_id: str) -> None:
        """A fresh session for this conversation now exists (start screencast for viewers)."""
        ...

    def on_session_gone(self, conversation_id: str) -> None:
        """The conversation's session was dropped / recycled (tell viewers session_closed)."""
        ...

    def is_watched(self, conversation_id: str) -> bool:
        """True while ≥1 live viewer is attached — spares the session from idle reaping."""
        ...


@dataclass
class _Entry:
    session: BrowserSession
    keyframes: KeyframeTracker = field(default_factory=KeyframeTracker)
    # Set while a user is actively driving this session by hand (M2 接管); None otherwise.
    takeover: TakeoverMark | None = None


async def _default_factory(request: BrowserSessionRequest) -> BrowserSession:
    """Open a real gVisor browser session via the sandbox provider's session surface."""
    from agentcore.workspace.locate import _default_server_sandbox

    sandbox = _default_server_sandbox()
    supports = getattr(sandbox, "supports_browser_sessions", None)
    if supports is None or not supports():
        from agentcore.tools.sandbox.browser.protocol import BrowserSessionError

        raise BrowserSessionError("当前后端不支持云端浏览器会话（需要 gVisor 沙箱）")
    return await sandbox.open_browser_session(request)


class BrowserSessionRegistry:
    """Process-wide ``conversation_id → browser session`` map with TTL + concurrency."""

    def __init__(
        self,
        *,
        factory: SessionFactory | None = None,
        max_sessions: int | None = None,
        idle_ttl_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
    ) -> None:
        self._factory = factory or _default_factory
        self._max_sessions = max_sessions
        self._idle_ttl = idle_ttl_seconds
        self._max_lifetime = max_lifetime_seconds
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # M1 live hub (D13): notified on create/drop, consulted for watch-based TTL sparing.
        self._observer: BrowserSessionObserver | None = None
        # M2 takeover (D17): completes the durable record on every session teardown that
        # still carries an un-ended takeover. Wired by the takeover service.
        self._takeover_finalizer: TakeoverFinalizer | None = None

    def set_observer(self, observer: BrowserSessionObserver | None) -> None:
        """Wire the live hub so this registry can announce sessions + spare watched ones."""
        self._observer = observer

    def set_takeover_finalizer(self, finalizer: TakeoverFinalizer | None) -> None:
        """Wire the takeover service so a dropped session's open record gets completed."""
        self._takeover_finalizer = finalizer

    # -- M2 takeover state (D16/D17): the entry is the in-memory source of truth ----------
    def is_taken_over(self, conversation_id: str) -> bool:
        """True while a live session for this conversation is under user takeover."""
        entry = self._live(conversation_id)
        return entry is not None and entry.takeover is not None

    def takeover_mark(self, conversation_id: str) -> TakeoverMark | None:
        """The active takeover mark for a live session, or None."""
        entry = self._live(conversation_id)
        return entry.takeover if entry is not None else None

    def begin_takeover(self, conversation_id: str, mark: TakeoverMark) -> bool:
        """Pin ``mark`` onto the conversation's live session; False if none is live."""
        entry = self._live(conversation_id)
        if entry is None:
            return False
        entry.takeover = mark
        logger.info("browser.takeover_marked", conversation_id=conversation_id)
        return True

    def end_takeover(self, conversation_id: str) -> TakeoverMark | None:
        """Clear + return the active takeover mark (explicit end), or None if not marked.

        Clearing here BEFORE any drop ensures an explicit end never double-finalizes: a
        later teardown finds no mark and skips the finalizer.
        """
        entry = self._entries.get(conversation_id)
        if entry is None or entry.takeover is None:
            return None
        mark = entry.takeover
        entry.takeover = None
        return mark

    # -- config (read live so a test / ops change is honored) -------------------
    @property
    def max_sessions(self) -> int:
        if self._max_sessions is not None:
            return self._max_sessions
        return int(settings.browser_max_sessions)

    @property
    def idle_ttl(self) -> float:
        if self._idle_ttl is not None:
            return self._idle_ttl
        return float(settings.browser_session_idle_ttl_seconds)

    @property
    def max_lifetime(self) -> float:
        return (
            self._max_lifetime
            if self._max_lifetime is not None
            else float(settings.browser_session_max_lifetime_seconds)
        )

    def _lock_for(self, conversation_id: str) -> asyncio.Lock:
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation_id] = lock
        return lock

    def _expired(self, entry: _Entry, now: float) -> bool:
        s = entry.session
        # Max lifetime always wins — even a watched (live-tab) session recycles past it so a
        # pinned tab cannot keep a ~1GB sandbox forever (D13).
        if (now - s.created_at) > self.max_lifetime:
            return True
        if (now - s.last_used) > self.idle_ttl:
            # Idle — but spare a session that has live viewers attached (open 直播 tab).
            watched = self._observer is not None and self._observer.is_watched(s.conversation_id)
            return not watched
        return False

    def _live(self, conversation_id: str) -> _Entry | None:
        entry = self._entries.get(conversation_id)
        if entry is None:
            return None
        if not entry.session.alive or self._expired(entry, time.time()):
            return None
        return entry

    def peek(self, conversation_id: str) -> BrowserSession | None:
        """The conversation's live session WITHOUT creating one (live view: no session ⇒ None)."""
        entry = self._live(conversation_id)
        return entry.session if entry is not None else None

    def _notify_ready(self, conversation_id: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer.on_session_ready(conversation_id)
        except Exception:  # noqa: BLE001 - a hub hiccup must not break session creation
            logger.warning("browser.observer_ready_failed", conversation_id=conversation_id)

    def _notify_gone(self, conversation_id: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer.on_session_gone(conversation_id)
        except Exception:  # noqa: BLE001 - a hub hiccup must not break teardown
            logger.warning("browser.observer_gone_failed", conversation_id=conversation_id)

    async def acquire(
        self, request: BrowserSessionRequest
    ) -> tuple[BrowserSession, KeyframeTracker]:
        """Get the conversation's live session (creating it lazily), plus its keyframes.

        Raises :class:`BrowserSessionsBusyError` when the concurrency cap is reached and no
        idle session can be reclaimed.
        """
        cid = request.conversation_id
        entry = self._live(cid)
        if entry is not None:
            return entry.session, entry.keyframes

        async with self._lock_for(cid):
            entry = self._live(cid)  # re-check under the lock (parallel tool calls)
            if entry is not None:
                return entry.session, entry.keyframes
            # Drop a dead/expired session for this conversation before recreating.
            if cid in self._entries:
                await self._drop(cid, reason="stale")
            await self._enforce_capacity()
            session = await self._factory(request)
            new_entry = _Entry(session=session)
            self._entries[cid] = new_entry
            logger.info("browser.registry_created", conversation_id=cid, live=len(self._entries))
            # Announce so the live hub can start screencast for any already-attached viewers.
            self._notify_ready(cid)
            return new_entry.session, new_entry.keyframes

    async def _enforce_capacity(self) -> None:
        if len(self._entries) < self.max_sessions:
            return
        await self.reap()
        if len(self._entries) >= self.max_sessions:
            raise BrowserSessionsBusyError(
                f"云端浏览器会话已满（并发上限 {self.max_sessions}）。"
                "请稍后重试，或结束其它对话的浏览器会话后再试。"
            )

    async def reap(self) -> int:
        """Close idle / over-lifetime / dead sessions. Returns how many were closed.

        Called lazily by the capacity gate and periodically by the lifespan loop.
        """
        now = time.time()
        stale = [
            cid
            for cid, entry in self._entries.items()
            if (not entry.session.alive) or self._expired(entry, now)
        ]
        for cid in stale:
            await self._drop(cid, reason="reaped")
        return len(stale)

    async def close(self, conversation_id: str) -> None:
        """Cascade cleanup for one conversation (deletion / explicit close)."""
        if conversation_id in self._entries:
            await self._drop(conversation_id, reason="closed")
        self._locks.pop(conversation_id, None)

    async def close_all(self) -> None:
        for cid in list(self._entries):
            await self._drop(cid, reason="shutdown")
        self._locks.clear()

    async def _drop(self, conversation_id: str, *, reason: str) -> None:
        entry = self._entries.pop(conversation_id, None)
        if entry is None:
            return
        # Complete the durable takeover record BEFORE teardown so it lands on EVERY end path
        # (reap / crash / shutdown / delete) — D17. Cleared explicit-end marks are already
        # gone, so this only fires for a still-active takeover.
        if entry.takeover is not None:
            await self._finalize_takeover(entry.takeover, reason)
            entry.takeover = None
        try:
            await entry.session.close()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            logger.warning("browser.registry_close_failed", conversation_id=conversation_id)
        logger.info("browser.registry_dropped", conversation_id=conversation_id, reason=reason)
        # Tell any live viewers the session they were watching is gone (session_closed).
        self._notify_gone(conversation_id)

    async def _finalize_takeover(self, mark: TakeoverMark, reason: str) -> None:
        finalizer = self._takeover_finalizer
        if finalizer is None:
            return
        try:
            await finalizer(mark, reason)
        except Exception:  # noqa: BLE001 - a留档 write failure must not break teardown
            logger.warning("browser.takeover_finalize_failed", record_id=mark.record_id)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, conversation_id: object) -> bool:
        return conversation_id in self._entries


_registry: BrowserSessionRegistry | None = None


def default_browser_session_registry() -> BrowserSessionRegistry:
    """The process-wide browser session registry (shared by tools + the reaper)."""
    global _registry
    if _registry is None:
        _registry = BrowserSessionRegistry()
    return _registry


async def browser_reaper_loop() -> None:
    """Background sweep that recycles idle / over-lifetime browser sandboxes.

    Mirrors the other lifespan retention loops (main.py). The active reaper is the
    backstop for the lazy on-access checks: a conversation that goes quiet still
    releases its ~1GB sandbox within the idle TTL instead of pinning it forever.
    """
    interval = float(settings.browser_reaper_interval_seconds)
    registry = default_browser_session_registry()
    while True:
        await asyncio.sleep(interval)
        try:
            closed = await registry.reap()
            if closed:
                logger.info("browser.reaper_swept", closed=closed, live=len(registry))
        except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
            logger.warning("browser.reaper_error")


async def shutdown_browser_sessions() -> None:
    """Close every live session + the shared proxy (lifespan shutdown)."""
    if _registry is not None:
        await _registry.close_all()
    from agentcore.tools.sandbox.browser.proxy import shutdown_browser_proxy

    await shutdown_browser_proxy()
