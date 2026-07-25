"""BrowserTakeoverService — the M2 user-takeover state machine (提案 · D16/D17).

Thin policy + durable-record layer over the session registry, which is the single
in-memory source of truth for「is this session under user takeover」(a mark on the entry).
This service enforces the D16 preconditions, brackets the ``browser_takeovers`` audit record
around an episode, and — wired as the registry's takeover finalizer — completes that record
on **every** teardown path (explicit end / reap / crash / shutdown / delete).

D16 接管时机: a takeover may START only when there is NO running turn (``turn_runs`` 判定 —
an ask_user-paused turn has already收口 out of the registry, so its window is open; a turn
awaiting a GRANTABLE approval is still running, so it is not) AND a live browser session
exists. **Narrow exception (browser_login):** while a turn is still running, if there is a
pending ``InteractionKind.ESCALATION`` whose payload has ``browser_login`` truthy, start is
allowed so the user can complete a login the AI hard-rejected (password never touches AI).
During takeover the ``browser_*`` tools return a busy error (they consult the registry mark),
and input injection refreshes the session's idle timer.

Nothing here touches frames or key/text content (D17): the record carries only who/when/why.
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

    async def create(self, *, conversation_id: str, user_id: str) -> tuple[str, datetime]:
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

    async def create(self, *, conversation_id: str, user_id: str) -> tuple[str, datetime]:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import BrowserTakeoverRepository

        async with async_session_factory() as session:
            return await BrowserTakeoverRepository(session).create(
                conversation_id=conversation_id, user_id=user_id
            )

    async def finalize(self, *, record_id: str, reason: str) -> bool:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import BrowserTakeoverRepository

        async with async_session_factory() as session:
            return await BrowserTakeoverRepository(session).finalize(
                record_id=record_id, reason=reason
            )


# The distinguishable outcomes the takeover endpoint response carries (D16: start前置三错误
# 可区分；接管状态由端点响应承载). Not HTTP errors — the state IS the response.
TakeoverReason = str  # started | ended | already_active | turn_running | no_session | not_active


@dataclass(frozen=True)
class TakeoverResult:
    """The takeover state an endpoint returns (carries the distinguishable reason)."""

    active: bool
    reason: TakeoverReason
    record_id: str | None = None
    started_at: datetime | None = None


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
        self._has_running_turn = has_running_turn
        self._has_browser_login_pending = has_browser_login_pending
        # Wire the finalizer so every session drop completes an open takeover record.
        self._reg().set_takeover_finalizer(self._finalize)

    def _reg(self) -> BrowserSessionRegistry:
        # NOTE: ``is not None`` — an empty BrowserSessionRegistry is falsy (it defines
        # __len__), so ``self._registry or default(...)`` would wrongly fall through.
        return self._registry if self._registry is not None else default_browser_session_registry()

    def _running(self, conversation_id: str) -> bool:
        """Whether a turn is currently RUNNING for this conversation (D16 判定)."""
        if self._has_running_turn is not None:
            return self._has_running_turn(conversation_id)
        from agentcore.runtime.turn_runs import turn_runs

        run = turn_runs.get(conversation_id)
        return run is not None and not run.task.done()

    def _browser_login_pending(self, conversation_id: str) -> bool:
        """True when a pending ESCALATION asks for user browser login (D16 窄例外)."""
        if self._has_browser_login_pending is not None:
            return self._has_browser_login_pending(conversation_id)
        from agentcore.runtime.interaction import InteractionKind, default_interaction_registry

        for req in default_interaction_registry().list_pending(conversation_id):
            if req.kind is InteractionKind.ESCALATION and (req.payload or {}).get(
                "browser_login"
            ):
                return True
        return False

    def is_active(self, conversation_id: str) -> bool:
        """True while the conversation's browser is under user takeover (tool/409 gate)."""
        return self._reg().is_taken_over(conversation_id)

    async def start(self, conversation_id: str, user_id: str) -> TakeoverResult:
        """Begin a takeover if allowed; return the resulting state (D16 preconditions).

        Precedence: already_active → turn_running → no_session → started. All non-``started``
        outcomes are distinguishable via ``reason`` (no side effects on failure).

        ``turn_running`` is skipped when a pending escalate carries ``browser_login``
        (login-takeover narrow exception); no_session / started logic still applies.
        """
        reg = self._reg()
        mark = reg.takeover_mark(conversation_id)
        if mark is not None:
            return TakeoverResult(
                active=True,
                reason="already_active",
                record_id=mark.record_id,
                started_at=mark.started_at,
            )
        if self._running(conversation_id) and not self._browser_login_pending(conversation_id):
            return TakeoverResult(active=False, reason="turn_running")
        if reg.peek(conversation_id) is None:
            return TakeoverResult(active=False, reason="no_session")

        record_id, started_at = await self._store.create(
            conversation_id=conversation_id, user_id=user_id
        )
        new_mark = TakeoverMark(record_id=record_id, user_id=user_id, started_at=started_at)
        if not reg.begin_takeover(conversation_id, new_mark):
            # The session vanished between the peek and the mark (rare). Close the record we
            # just opened so it is never left dangling, and report no_session.
            await self._store.finalize(record_id=record_id, reason="no_session")
            return TakeoverResult(active=False, reason="no_session")
        logger.info("browser.takeover_started", conversation_id=conversation_id)
        return TakeoverResult(
            active=True, reason="started", record_id=record_id, started_at=started_at
        )

    async def end(self, conversation_id: str) -> TakeoverResult:
        """End a takeover if active (idempotent); complete its record. Never errors."""
        reg = self._reg()
        mark = reg.takeover_mark(conversation_id)
        if mark is None:
            return TakeoverResult(active=False, reason="not_active")
        await self._store.finalize(record_id=mark.record_id, reason="user_end")
        reg.end_takeover(conversation_id)
        logger.info("browser.takeover_ended", conversation_id=conversation_id)
        return TakeoverResult(active=False, reason="ended", record_id=mark.record_id)

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
