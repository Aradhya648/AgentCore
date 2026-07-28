"""BrowserTakeoverService — the M2 user-takeover state machine (提案 · D16/D17 · D8).

Thin policy + durable-record layer over the session registry, which is the single
in-memory source of truth for「is this session under user takeover」(a mark on the entry).
This service brackets the ``browser_takeovers`` audit record around an episode, and —
wired as the registry's takeover finalizer — completes that record on **every** teardown
path (explicit end / reap / crash / shutdown / delete).

D8 接管时机: a takeover may START whenever a live browser session exists (user may
interrupt a running turn at any time). The legacy ``turn_running`` gate is abolished.
During takeover the ``browser_*`` tools return ``metadata.code=user_in_control``.

Optional ``session_id`` selects which tab; omitting it resolves via the registry's
run-bound / unique / active rules (conversation-level thin wrap).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentcore.core.logging import get_logger
from agentcore.runtime.browser.registry import (
    BrowserSessionRegistry,
    TakeoverMark,
    default_browser_session_registry,
)

logger = get_logger(__name__)


class TakeoverStore(Protocol):
    """Durable store port for takeover episodes (DB-backed in prod, fake in tests)."""

    async def create(
        self,
        *,
        conversation_id: str,
        user_id: str,
        session_id: str | None = None,
    ) -> tuple[str, datetime]:
        """Insert an in-progress episode; return ``(record_id, started_at)``."""
        ...

    async def finalize(self, *, record_id: str, reason: str) -> bool:
        """Close an OPEN episode (idempotent); return whether this call closed it."""
        ...


class _DbTakeoverStore:
    """Default store: one short-lived primary-pool session per op (works off the request).

    Finalize runs from background teardown (reap / shutdown) with no request session, so the
    store owns its own sessions rather than borrowing one.
    """

    async def create(
        self,
        *,
        conversation_id: str,
        user_id: str,
        session_id: str | None = None,
    ) -> tuple[str, datetime]:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import BrowserTakeoverRepository

        async with async_session_factory() as session:
            return await BrowserTakeoverRepository(session).create(
                conversation_id=conversation_id,
                user_id=user_id,
                session_id=session_id,
            )

    async def finalize(self, *, record_id: str, reason: str) -> bool:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import BrowserTakeoverRepository

        async with async_session_factory() as session:
            return await BrowserTakeoverRepository(session).finalize(
                record_id=record_id, reason=reason
            )


# Distinguable outcomes the takeover endpoint response carries. ``turn_running`` remains in
# the Literal for wire compat but is never produced after D8 (anytime takeover).
TakeoverReason = str  # started | ended | already_active | no_session | not_active | turn_running


@dataclass(frozen=True)
class TakeoverResult:
    """The takeover state an endpoint returns (carries the distinguishable reason)."""

    active: bool
    reason: TakeoverReason
    record_id: str | None = None
    started_at: datetime | None = None
    session_id: str | None = None


class BrowserTakeoverService:
    """User-takeover state machine + durable留档 for one process (singleton in prod)."""

    def __init__(
        self,
        *,
        registry: BrowserSessionRegistry | None = None,
        store: TakeoverStore | None = None,
        has_running_turn: Callable[[str], bool] | None = None,
        has_browser_login_pending: Callable[[str], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._store: TakeoverStore = store or _DbTakeoverStore()
        # Retained for call-site compat / tests; D8 no longer gates start on these.
        self._has_running_turn = has_running_turn
        self._has_browser_login_pending = has_browser_login_pending
        # Wire the finalizer so every session drop completes an open takeover record.
        self._reg().set_takeover_finalizer(self._finalize)

    def _reg(self) -> BrowserSessionRegistry:
        # NOTE: ``is not None`` — an empty BrowserSessionRegistry is falsy (it defines
        # __len__), so ``self._registry or default(...)`` would wrongly fall through.
        return self._registry if self._registry is not None else default_browser_session_registry()

    def is_active(
        self, conversation_id: str, *, session_id: str | None = None
    ) -> bool:
        """True while the resolved browser session is under user takeover (tool/409 gate)."""
        return self._reg().is_taken_over(conversation_id, session_id=session_id)

    async def start(
        self,
        conversation_id: str,
        user_id: str,
        *,
        session_id: str | None = None,
    ) -> TakeoverResult:
        """Begin a takeover if a live session exists (D8: anytime; no turn_running gate).

        Precedence: already_active → no_session → started. All non-``started`` outcomes are
        distinguishable via ``reason`` (no side effects on failure).
        """
        reg = self._reg()
        mark = reg.takeover_mark(conversation_id, session_id=session_id)
        if mark is not None:
            sid = reg.resolve_session_id(conversation_id, session_id=session_id)
            return TakeoverResult(
                active=True,
                reason="already_active",
                record_id=mark.record_id,
                started_at=mark.started_at,
                session_id=sid,
            )
        if reg.peek(conversation_id, session_id=session_id) is None:
            return TakeoverResult(active=False, reason="no_session", session_id=session_id)

        sid = reg.resolve_session_id(conversation_id, session_id=session_id)
        record_id, started_at = await self._store.create(
            conversation_id=conversation_id, user_id=user_id, session_id=sid
        )
        new_mark = TakeoverMark(record_id=record_id, user_id=user_id, started_at=started_at)
        if not reg.begin_takeover(conversation_id, new_mark, session_id=session_id):
            # The session vanished between the peek and the mark (rare). Close the record we
            # just opened so it is never left dangling, and report no_session.
            await self._store.finalize(record_id=record_id, reason="no_session")
            return TakeoverResult(active=False, reason="no_session", session_id=session_id)
        logger.info(
            "browser.takeover_started",
            conversation_id=conversation_id,
            session_id=sid,
        )
        return TakeoverResult(
            active=True,
            reason="started",
            record_id=record_id,
            started_at=started_at,
            session_id=sid,
        )

    async def end(
        self,
        conversation_id: str,
        *,
        session_id: str | None = None,
    ) -> TakeoverResult:
        """End a takeover if active (idempotent); complete its record. Never errors."""
        reg = self._reg()
        mark = reg.takeover_mark(conversation_id, session_id=session_id)
        if mark is None:
            return TakeoverResult(active=False, reason="not_active", session_id=session_id)
        sid = reg.resolve_session_id(conversation_id, session_id=session_id)
        await self._store.finalize(record_id=mark.record_id, reason="user_end")
        reg.end_takeover(conversation_id, session_id=session_id)
        logger.info(
            "browser.takeover_ended",
            conversation_id=conversation_id,
            session_id=sid,
        )
        return TakeoverResult(
            active=False, reason="ended", record_id=mark.record_id, session_id=sid
        )

    async def _finalize(self, mark: TakeoverMark, reason: str) -> None:
        """Registry finalizer: complete a record when its session is torn down (D17)."""
        await self._store.finalize(record_id=mark.record_id, reason=reason)
        logger.info("browser.takeover_finalized", record_id=mark.record_id, reason=reason)


_service: BrowserTakeoverService | None = None


def default_browser_takeover_service() -> BrowserTakeoverService:
    """The process-wide takeover service, wired to the default session registry."""
    global _service
    if _service is None:
        _service = BrowserTakeoverService()
    return _service
