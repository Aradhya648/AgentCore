"""Two-layer memory orchestration (episodic session digests → semantic consolidation).

Episodic (live path): each finished turn arms a per-conversation idle debounce /
turn-cap. When it fires, a ≤200-char session summary is appended under ``情景/`` and
a light ``memory_updated`` tip is pushed — never a direct preference/profile write.

Semantic (batch): after an episodic write (and on the periodic sweeper), if undigested
episodes ≥ ``memory_semantic_min_episodes`` OR age since last success ≥
``memory_semantic_max_age_hours``, one consolidator pass rewrites always-files and
applies topic ops, then pushes a diff card.

Open-turn deferral, per-user locks, and ``memory_synced_at`` watermarks are unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from agentcore.billing.gate import resolve_and_gate_background
from agentcore.config import settings
from agentcore.conversation.history import load_recent_history
from agentcore.conversation.store.merge import (
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INCOMPLETE,
    MESSAGE_STATUS_RUNNING,
)
from agentcore.core.log_context import log_context
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories import (
    ConversationRepository,
    MemoryUpdateRepository,
    MessageRepository,
    PausedTurnRepository,
    TurnLeaseRepository,
)
from agentcore.llm.factory import build_provider
from agentcore.llm.resolve import resolve_turn_model as resolve_user_model
from agentcore.memory.episodic import (
    LLMEpisodicSummarizer,
    append_episode,
    fallback_episode_summary,
    list_undigested_episodes,
    load_scope_meta,
    mark_episodes_digested,
    should_run_semantic,
)
from agentcore.memory.locks import user_memory_lock
from agentcore.memory.maintenance import MemoryUpdateItem
from agentcore.memory.semantic import (
    LLMSemanticConsolidator,
    consolidate_semantic_memory,
)
from agentcore.memory.store import MemoryStore, default_memory_store
from agentcore.messaging.hub import default_chat_hub
from agentcore.runtime.events.types import FinishReason

logger = get_logger(__name__)

# Terminal states that must not feed episodic/semantic memory (失败/中断回合跳过沉淀).
_ABNORMAL_FINISH_REASONS = frozenset(
    {
        FinishReason.CANCELLED.value,
        FinishReason.INTERRUPTED.value,
        FinishReason.ERROR.value,
        FinishReason.PAUSED.value,
    }
)
_ABNORMAL_STATUSES = frozenset(
    {
        MESSAGE_STATUS_INCOMPLETE,
        MESSAGE_STATUS_FAILED,
        MESSAGE_STATUS_RUNNING,
    }
)
# Historical interrupt body chrome (writers stopped appending these). Kept so
# older rows still skip memory consolidation when metadata is thin.
_INCOMPLETE_NOTE = (
    "（已停止，本回合未完成。下面是已完成队员的产出，已为你保留；如需继续，可重新发送消息。）"
)
_INCOMPLETE_SUFFIX = "（已停止，本回合未完成——以上为已生成部分；如需继续，可重新发送消息。）"
_INCOMPLETE_NOTE_LEGACY = (
    "（连接中断，本回合未完成。下面是已完成队员的产出，已为你保留；如需继续，可重新发送消息。）"
)
_INCOMPLETE_SUFFIX_LEGACY = (
    "（连接中断，本回合未完成——以上为已生成部分；如需继续，可重新发送消息。）"
)
_INTERRUPTED_NOTE_LEGACY = "（已中断，可重试）"


def abnormal_turn_skip_reason(
    *,
    usage: dict | None,
    content: str | None,
    has_assistant: bool,
) -> str | None:
    """Return a short reason when the latest assistant turn must not feed memory.

    Skips cancelled / incomplete / failed / still-running turns and turns with no
    substantial assistant settlement. Normal completions (``end_turn`` and other
    finished outcomes with real content) return ``None``.
    """
    if not has_assistant:
        return "no_assistant"
    meta = usage if isinstance(usage, dict) else {}
    status = meta.get("status")
    finish = meta.get("finish_reason")
    if meta.get("incomplete") is True:
        return "incomplete"
    if isinstance(status, str) and status in _ABNORMAL_STATUSES:
        return f"status:{status}"
    if isinstance(finish, str) and finish in _ABNORMAL_FINISH_REASONS:
        return f"finish_reason:{finish}"
    body = (content or "").strip()
    if not body:
        return "empty_assistant"
    if (
        body in (_INCOMPLETE_NOTE, _INCOMPLETE_NOTE_LEGACY, _INTERRUPTED_NOTE_LEGACY)
        or body.endswith(_INCOMPLETE_SUFFIX)
        or body.endswith(_INCOMPLETE_SUFFIX_LEGACY)
        or body.endswith(_INTERRUPTED_NOTE_LEGACY)
    ):
        # Incomplete salvage note alone (or only chrome after a blank stream).
        cleaned = (
            body.replace(_INCOMPLETE_SUFFIX, "")
            .replace(_INCOMPLETE_NOTE, "")
            .replace(_INCOMPLETE_SUFFIX_LEGACY, "")
            .replace(_INCOMPLETE_NOTE_LEGACY, "")
            .replace(_INTERRUPTED_NOTE_LEGACY, "")
            .strip()
        )
        if not cleaned:
            return "empty_incomplete"
        # Streamed text + incomplete suffix still counts as incomplete settlement.
        if status != MESSAGE_STATUS_COMPLETE and finish not in (
            FinishReason.END_TURN.value,
            FinishReason.MAX_ROUNDS.value,
            FinishReason.DEGRADED.value,
            FinishReason.UNPRODUCTIVE.value,
        ):
            return "incomplete_body"
    # Legacy rows with content but no usage metadata: allow (pre-feature history).
    if status is None and finish is None:
        return None
    # Explicit complete / known finished reasons with body → eligible.
    if status == MESSAGE_STATUS_COMPLETE:
        return None
    if isinstance(finish, str) and finish in {
        FinishReason.END_TURN.value,
        FinishReason.MAX_ROUNDS.value,
        FinishReason.DEGRADED.value,
        FinishReason.UNPRODUCTIVE.value,
    }:
        return None
    return "unsettled"


async def conversation_turn_open(session, conversation_id: str) -> bool:
    """True when the conversation is MID-TURN: durably paused or live-running."""
    if await PausedTurnRepository(session).exists_for_conversation(conversation_id):
        return True
    fresh_after = datetime.now(UTC) - timedelta(seconds=settings.turn_lease_ttl_seconds)
    return await TurnLeaseRepository(session).exists_fresh_for_conversation(
        conversation_id, after=fresh_after
    )


async def _latest_assistant_row(
    session, conversation_id: str
) -> tuple[dict | None, str | None, bool]:
    """Latest assistant message's ``(usage, content, found)`` for settlement gating."""
    rows = await MessageRepository(session).list_recent(conversation_id, limit=40)
    for msg in reversed(rows):
        if msg.role == "assistant":
            usage = msg.usage if isinstance(msg.usage, dict) else None
            return usage, msg.content, True
    return None, None, False


async def _publish_memory_updated(
    *,
    user_id: str,
    conversation_id: str,
    kind: str,
    update_payload: dict | None,
) -> None:
    """Best-effort firehose nudge — both layers require a visible notice (no silent writes)."""
    with contextlib.suppress(Exception):
        event: dict = {
            "type": "memory_updated",
            "conversation_id": conversation_id,
            "kind": kind,
        }
        if update_payload is not None:
            event["update"] = update_payload
        await default_chat_hub().publish([user_id], event)


async def _record_and_publish(
    *,
    conversation_id: str,
    user_id: str,
    kind: str,
    items: list[MemoryUpdateItem],
    summary: str | None = None,
) -> None:
    items_payload = [asdict(it) for it in items]
    async with async_session_factory() as session:
        row = await MemoryUpdateRepository(session).record(
            conversation_id=conversation_id,
            user_id=user_id,
            items=items_payload,
            kind=kind,
            summary=summary,
        )
        update_payload = {
            "id": row.id,
            "conversation_id": conversation_id,
            "created_at": row.created_at.isoformat(),
            "kind": kind,
            "summary": summary,
            "items": items_payload,
        }
    await _publish_memory_updated(
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,
        update_payload=update_payload,
    )


async def run_semantic_for_scope(
    *,
    user_id: str,
    conversation_id: str,
    folder_id: str | None,
    store: MemoryStore,
    credentials,
) -> bool:
    """Run one semantic consolidation for a (user, scope) when trigger conditions hold."""
    scope = folder_id
    undigested = await list_undigested_episodes(store, user_id, scope=scope)
    meta = await load_scope_meta(store, user_id, scope=scope)
    oldest: datetime | None = None
    if undigested:
        try:
            oldest = datetime.fromisoformat(undigested[0].created_at.replace("Z", "+00:00"))
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
        except ValueError:
            oldest = None
    if not should_run_semantic(
        undigested_count=len(undigested),
        last_semantic_at=meta.last_semantic_at,
        min_episodes=settings.memory_semantic_min_episodes,
        max_age_hours=settings.memory_semantic_max_age_hours,
        oldest_undigested_at=oldest,
    ):
        return False
    if credentials is None:
        return False

    model = resolve_user_model(credentials)
    provider = build_provider(credentials, purpose="platform_internal")
    collected: list[MemoryUpdateItem] = []
    try:
        outcome = await consolidate_semantic_memory(
            user_id=user_id,
            episodes=undigested,
            consolidator=LLMSemanticConsolidator(provider, model=model),
            store=store,
            today=datetime.now(UTC).date().isoformat(),
            section_cap=settings.memory_section_bullet_cap,
            max_topic_files=settings.memory_max_topic_files,
            folder_id=folder_id,
            collect_items=collected,
        )
    finally:
        await provider.close()

    if outcome is None:
        # Parse/timeout/exception — leave episodes undigested for a later retry.
        return False

    # Success (changed or noop): mark digested so the same summaries are not re-merged.
    await mark_episodes_digested(
        store,
        user_id,
        [ep.id for ep in undigested],
        scope=scope,
        consolidated_at=datetime.now(UTC),
    )
    if outcome:
        await _record_and_publish(
            conversation_id=conversation_id,
            user_id=user_id,
            kind="semantic",
            items=collected,
            summary=None if collected else "记忆已整理",
        )
    logger.info(
        "memory.semantic_consolidated",
        user_id=user_id,
        conversation_id=conversation_id,
        episodes=len(undigested),
        changed=outcome,
    )
    return outcome


async def consolidate_conversation(
    conversation_id: str, *, store: MemoryStore | None = None
) -> bool:
    """Write one episodic session summary for a settled conversation; maybe semantic.

    Returns True when an episodic summary was written (semantic may or may not follow).
    Never raises.
    """
    store = store or default_memory_store()
    try:
        async with user_memory_lock_for(conversation_id) as user_id:
            if user_id is None:
                return False
            async with async_session_factory() as session:
                latest = await MessageRepository(session).latest_created_at(conversation_id)
                conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
                if conv is None or latest is None:
                    return False
                if await conversation_turn_open(session, conversation_id):
                    logger.info(
                        "memory.consolidation_deferred_open_turn",
                        conversation_id=conversation_id,
                    )
                    return False
                usage, assistant_content, has_assistant = await _latest_assistant_row(
                    session, conversation_id
                )
                skip_reason = abnormal_turn_skip_reason(
                    usage=usage,
                    content=assistant_content,
                    has_assistant=has_assistant,
                )
                if skip_reason is not None:
                    # Abnormal terminal turn: skip episodic entirely and advance the
                    # watermark so the sweeper does not retry until new messages arrive.
                    await ConversationRepository(session).set_memory_synced_at(
                        conversation_id, latest
                    )
                    logger.debug(
                        "memory.consolidation_skipped_abnormal_turn",
                        conversation_id=conversation_id,
                        reason=skip_reason,
                        finish_reason=(
                            usage.get("finish_reason") if isinstance(usage, dict) else None
                        ),
                        status=usage.get("status") if isinstance(usage, dict) else None,
                    )
                    return False
                synced = conv.memory_synced_at
                if synced is not None and latest <= synced:
                    return False
                folder_id = conv.folder_id
                window = await load_recent_history(
                    session,
                    conversation_id,
                    max_messages=settings.memory_consolidation_window_messages,
                )
                credentials = await resolve_and_gate_background(
                    session, user_id, purpose="memory"
                )

            if window and credentials is None:
                return False

            wrote_episodic = False
            if window:
                model = resolve_user_model(credentials)
                provider = build_provider(credentials, purpose="platform_internal")
                try:
                    summarizer = LLMEpisodicSummarizer(provider, model=model)
                    summary = await summarizer.summarize(
                        window, max_chars=settings.memory_episodic_summary_max_chars
                    )
                    if not summary.strip():
                        summary = fallback_episode_summary(
                            window, max_chars=settings.memory_episodic_summary_max_chars
                        )
                    episode = await append_episode(
                        store,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        summary=summary,
                        scope=folder_id,
                        max_chars=settings.memory_episodic_summary_max_chars,
                    )
                    wrote_episodic = True
                    await _record_and_publish(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        kind="episodic",
                        items=[],
                        summary=episode.summary,
                    )
                finally:
                    await provider.close()

            async with async_session_factory() as session:
                await ConversationRepository(session).set_memory_synced_at(
                    conversation_id, latest
                )

            if wrote_episodic:
                with contextlib.suppress(Exception):
                    await run_semantic_for_scope(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        folder_id=folder_id,
                        store=store,
                        credentials=credentials,
                    )

            logger.info(
                "memory.consolidated",
                conversation_id=conversation_id,
                user_id=user_id,
                changed=wrote_episodic,
                layer="episodic",
            )
            return wrote_episodic
    except Exception as e:
        logger.warning("memory.consolidation_failed", conversation_id=conversation_id, error=str(e))
        return False


class _UserLockForConversation:
    """Resolve a conversation's owner, then hold that user's memory lock."""

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self._cm = None

    async def __aenter__(self) -> str | None:
        async with async_session_factory() as session:
            conv = await ConversationRepository(session).get_by_id_unscoped(self._conversation_id)
        if conv is None:
            return None
        self._cm = user_memory_lock(conv.user_id)
        await self._cm.__aenter__()
        return conv.user_id

    async def __aexit__(self, *exc) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(*exc)


def user_memory_lock_for(conversation_id: str) -> _UserLockForConversation:
    """Async-context wrapper yielding the owner user_id while holding their lock."""
    return _UserLockForConversation(conversation_id)


# --- Debounce scheduler (live path → episodic) --------------------------------

Runner = Callable[[str], Awaitable[object]]


class MemoryConsolidationScheduler:
    """Per-conversation debounce + turn-cap trigger for episodic summary writes."""

    def __init__(self, *, idle_seconds: float, turn_cap: int, runner: Runner) -> None:
        self._idle = idle_seconds
        self._turn_cap = turn_cap
        self._runner = runner
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._counts: dict[str, int] = {}
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, conversation_id: str) -> None:
        """Register a finished turn: arm/reset the debounce, or fire at the cap."""
        self._counts[conversation_id] = self._counts.get(conversation_id, 0) + 1
        if self._turn_cap and self._counts[conversation_id] >= self._turn_cap:
            self._fire(conversation_id)
            return
        self._cancel_timer(conversation_id)
        loop = asyncio.get_running_loop()
        self._timers[conversation_id] = loop.call_later(self._idle, self._fire, conversation_id)

    def _fire(self, conversation_id: str) -> None:
        self._cancel_timer(conversation_id)
        self._counts.pop(conversation_id, None)
        task = asyncio.ensure_future(self._run(conversation_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, conversation_id: str) -> None:
        try:
            with log_context(conversation_id=conversation_id):
                await self._runner(conversation_id)
        except Exception as e:
            logger.warning(
                "memory.consolidation_run_failed",
                conversation_id=conversation_id,
                error=str(e),
            )

    def _cancel_timer(self, conversation_id: str) -> None:
        timer = self._timers.pop(conversation_id, None)
        if timer is not None:
            timer.cancel()

    async def shutdown(self) -> None:
        """Cancel pending timers and await in-flight passes (clean lifespan exit)."""
        for timer in list(self._timers.values()):
            timer.cancel()
        self._timers.clear()
        self._counts.clear()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


_default_scheduler: MemoryConsolidationScheduler | None = None


def get_scheduler() -> MemoryConsolidationScheduler:
    """Process-wide scheduler bound to the real runner (lazy, settings-configured)."""
    global _default_scheduler
    if _default_scheduler is None:
        _default_scheduler = MemoryConsolidationScheduler(
            idle_seconds=settings.memory_consolidation_idle_seconds,
            turn_cap=settings.memory_consolidation_turn_cap,
            runner=consolidate_conversation,
        )
    return _default_scheduler


def schedule_consolidation(conversation_id: str) -> None:
    """Arm the debounce for a finished turn (no-op when the feature is disabled)."""
    if not settings.memory_consolidation_enabled:
        return
    get_scheduler().schedule(conversation_id)


async def shutdown_scheduler() -> None:
    """Flush the process-wide scheduler on app shutdown (no-op if never built)."""
    if _default_scheduler is not None:
        await _default_scheduler.shutdown()


# --- Periodic sweeper (backstop) ---------------------------------------------


async def consolidation_sweep_once() -> int:
    """One backstop sweep: episodic-write settled chats with un-synced messages."""
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.memory_consolidation_idle_seconds)
    async with async_session_factory() as session:
        pending = await ConversationRepository(session).list_pending_memory_consolidation(
            idle_before=cutoff,
            limit=settings.memory_consolidation_sweep_batch_limit,
        )
    for conversation_id in pending:
        with log_context(conversation_id=conversation_id):
            await consolidate_conversation(conversation_id)
    return len(pending)


async def consolidation_loop() -> None:
    """Forever: sleep, then run one backstop sweep. Cancelled cleanly on shutdown."""
    interval = settings.memory_consolidation_sweep_interval_seconds
    while True:
        try:
            await asyncio.sleep(interval)
            count = await consolidation_sweep_once()
            if count:
                logger.info("memory.consolidation_swept", count=count)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log = logger.error if is_schema_error(e) else logger.warning
            log("memory.consolidation_sweep_failed", error=str(e))
