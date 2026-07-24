"""Single closer for incomplete / interrupted turns (user stop · process kill · redrive).

Three historical writers (cancel salvage, lease sweeper, recover degrade) used to emit
divergent body copy and ``finish_reason`` values. All paths funnel here so terminal
chrome stays consistent (frontend maps ``interrupted`` → ``cancelled``).

After the durable incomplete write, this closer also best-effort reconciles the turn
cost ledger (``cost.recorded`` + ``messages.cost``) so /stop does not drop payroll.
"""

from __future__ import annotations

import contextlib
from enum import StrEnum
from typing import Any

from agentcore.conversation.store.merge import MESSAGE_STATUS_INCOMPLETE, pick_monotonic_content
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import MessageRepository, TurnJournalRepository
from agentcore.runtime.events import FinishReason
from agentcore.runtime.events.stream_checkpointer import (
    CHANNEL_CAPTAIN_CONTENT,
    CHANNEL_CAPTAIN_REASONING,
)
from agentcore.runtime.journal import journal_entries_from_display_runs, persist_turn_journal
from agentcore.runtime.journal.entries import KIND_TURN_END

logger = get_logger(__name__)

_TERMINAL_FINISH = frozenset(
    {
        FinishReason.CANCELLED.value,
        FinishReason.INTERRUPTED.value,
    }
)

# User-stop / cancel-path copy (matches CloudStore.salvage historical wording).
_USER_STOP_NOTE = (
    "（已停止，本回合未完成。下面是已完成队员的产出，已为你保留；如需继续，可重新发送消息。）"
)
_USER_STOP_SUFFIX = (
    "\n\n（已停止，本回合未完成——以上为已生成部分；如需继续，可重新发送消息。）"
)
# Process-kill / redrive-failed copy (sweeper salvage).
_INTERRUPTED_NOTE = "（已中断，可重试）"
_INTERRUPTED_SUFFIX = "\n\n（已中断，可重试）"
# True SSE / transport disconnect salvage (not user /stop) — reserved for
# disconnect-only writers; user_stop / CANCELLED use the「已停止」copy above.
_DISCONNECT_NOTE = (
    "（连接中断，本回合未完成。下面是已完成队员的产出，已为你保留；如需继续，可重新发送消息。）"
)
_DISCONNECT_SUFFIX = (
    "\n\n（连接中断，本回合未完成——以上为已生成部分；如需继续，可重新发送消息。）"
)


class TurnInterruptReason(StrEnum):
    USER_STOP = "user_stop"
    PROCESS_KILL = "process_kill"
    REDRIVE_FAILED = "redrive_failed"


def normalize_interrupt_reason(reason: str | TurnInterruptReason) -> TurnInterruptReason:
    """Map legacy sweeper / recover reason strings onto the closed enum."""
    if isinstance(reason, TurnInterruptReason):
        return reason
    raw = (reason or "").strip()
    if raw == TurnInterruptReason.USER_STOP.value:
        return TurnInterruptReason.USER_STOP
    if raw in (TurnInterruptReason.REDRIVE_FAILED.value, "redrive_unwired"):
        return TurnInterruptReason.REDRIVE_FAILED
    # no_dag / process_kill / unknown → process kill terminal
    return TurnInterruptReason.PROCESS_KILL


def finish_reason_for(reason: TurnInterruptReason) -> FinishReason:
    if reason is TurnInterruptReason.USER_STOP:
        return FinishReason.CANCELLED
    return FinishReason.INTERRUPTED


def compose_interrupt_body(content: str, *, reason: TurnInterruptReason) -> str:
    streamed = (content or "").strip()
    if reason is TurnInterruptReason.USER_STOP:
        return f"{streamed}{_USER_STOP_SUFFIX}" if streamed else _USER_STOP_NOTE
    return f"{streamed}{_INTERRUPTED_SUFFIX}" if streamed else _INTERRUPTED_NOTE


def _journal_has_turn_end(entries: list[dict] | None) -> bool:
    return any((e.get("kind") or "") == KIND_TURN_END for e in (entries or []))


def _already_terminal_incomplete(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    status = meta.get("status")
    finish = meta.get("finish_reason")
    incomplete = meta.get("incomplete") is True or status == MESSAGE_STATUS_INCOMPLETE
    return incomplete and finish in _TERMINAL_FINISH


async def _reconcile_interrupted_turn_cost(
    *,
    message_id: str,
    conversation_id: str,
    trace_id: str | None,
) -> None:
    """Best-effort turn ledger reconcile after interrupt close (stop / sweeper / kill).

    Successful LLM calls usually already sit in ``cost_calls``; interrupt closers
    historically skipped turn-end reconcile, so ``cost.recorded`` / ``messages.cost``
    never landed. Reuse the same ``reconcile_turn_cost_ledger`` + ``log_cost_recorded``
    path as cloud finalize with empty ``cost_runs`` (no forged orphans — vision sink
    may still be lost on cancel). Skip emit when ``messages.cost`` is already stamped
    so a second closer does not double-log ``cost.recorded``.
    """
    from agentcore.billing.turn_ledger import reconcile_turn_cost_ledger
    from agentcore.conversation.common import log_cost_recorded
    from agentcore.db.repositories import ConversationRepository, MessageRepository
    from agentcore.runtime.costing import aggregate_cost

    async with async_session_factory() as session:
        conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
        if conv is None or not conv.user_id:
            logger.warning(
                "cost.interrupt_reconcile_skipped",
                conversation_id=conversation_id,
                message_id=message_id,
                reason="conversation_missing",
            )
            return
        msg_repo = MessageRepository(session)
        existing = await msg_repo.get_by_id(message_id, conversation_id=conversation_id)
        if existing is not None and existing.cost:
            # Already stamped (prior interrupt reconcile or a later finalize) — DB
            # reconcile is idempotent, but cost.recorded must not double-emit.
            return
        try:
            ledger_rows = await reconcile_turn_cost_ledger(
                session,
                user_id=str(conv.user_id),
                conversation_id=conversation_id,
                message_id=message_id,
                cost_runs=[],
                trace_id=trace_id,
            )
        except Exception as e:
            await session.rollback()
            logger.warning(
                "cost.ledger_write_failed",
                conversation_id=conversation_id,
                message_id=message_id,
                error=str(e),
                source="interrupt",
            )
            return
        if not ledger_rows:
            return
        log_cost_recorded(conversation_id, message_id, ledger_rows)
        try:
            await msg_repo.set_cost(
                message_id,
                conversation_id=conversation_id,
                cost=dict(aggregate_cost(ledger_rows)),
            )
        except Exception as e:
            await session.rollback()
            logger.warning(
                "cost.message_column_write_failed",
                conversation_id=conversation_id,
                message_id=message_id,
                error=str(e),
                source="interrupt",
            )


async def close_turn_interrupted(
    *,
    message_id: str,
    conversation_id: str,
    reason: str | TurnInterruptReason,
    trace_id: str | None = None,
    content: str | None = None,
    reasoning_content: str | None = None,
    journal: list[dict[str, Any]] | None = None,
    load_stream_state: bool = False,
) -> bool:
    """Write incomplete + terminal ``turn_end`` for an interrupted turn.

    Returns ``True`` when the close write completed (or was already terminal).
    Returns ``False`` on hard failure so callers can keep the orphaned lease.
    """
    resolved = normalize_interrupt_reason(reason)
    finish = finish_reason_for(resolved)
    if not message_id:
        return False

    try:
        body_content = content
        body_reasoning = reasoning_content
        seg_content = ""
        seg_reasoning = ""
        if load_stream_state:
            from agentcore.conversation.store import get_cloud_store

            segments = await get_cloud_store().list_stream_segments(turn_id=message_id)
            by_ch = {s["channel"]: s.get("text") or "" for s in segments}
            seg_content = by_ch.get(CHANNEL_CAPTAIN_CONTENT) or ""
            seg_reasoning = by_ch.get(CHANNEL_CAPTAIN_REASONING) or ""

        async with async_session_factory() as session:
            existing = await MessageRepository(session).get_by_id(
                message_id, conversation_id=conversation_id
            )
            existing_usage = existing.usage if existing is not None else None
            resolved_trace = trace_id or (
                existing.trace_id if existing is not None else None
            )

            skip_upsert = _already_terminal_incomplete(
                existing_usage if isinstance(existing_usage, dict) else None
            )

            if not skip_upsert:
                existing_content = existing.content if existing else None
                existing_reasoning = (
                    existing.reasoning_content if existing else None
                )
                if load_stream_state:
                    raw = pick_monotonic_content(existing_content, seg_content)
                    body_reasoning = (
                        pick_monotonic_content(existing_reasoning, seg_reasoning) or None
                    )
                else:
                    raw = (
                        body_content
                        if body_content is not None
                        else (existing_content or "")
                    )
                    if body_reasoning is None and existing_reasoning:
                        body_reasoning = existing_reasoning
                body = compose_interrupt_body(raw or "", reason=resolved)
                await MessageRepository(session).upsert_assistant(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    content=body,
                    reasoning_content=body_reasoning,
                    trace_id=resolved_trace,
                    metadata={
                        "status": MESSAGE_STATUS_INCOMPLETE,
                        "incomplete": True,
                        "finish_reason": finish.value,
                        "interrupt_reason": resolved.value,
                    },
                    merge=True,
                )

            if journal is not None:
                # Best-effort display salvage. Progressive append-on-emit may already own
                # denser seqs; merge-mode persist (seq=0..n) can no-op and drop turn_end —
                # the ensure-append below is the reliable closer.
                await persist_turn_journal(
                    session,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    trace_id=resolved_trace or "",
                    entries=journal_entries_from_display_runs(
                        {
                            "events": journal,
                            "finish_reason": finish.value,
                        }
                    ),
                )
            # turn_end 必写：message 终态与 fold 的 finish_reason 同源。后台 execution
            # 事实在收口后继续追加（批次1）是特性——这里只保证收口时终态事实已落盘。
            entries = await TurnJournalRepository(session).load_owned(
                message_id, conversation_id
            )
            if not _journal_has_turn_end(entries or []):
                await TurnJournalRepository(session).append(
                    turn_id=message_id,
                    seq=None,
                    conversation_id=conversation_id,
                    trace_id=resolved_trace,
                    entry={
                        "kind": KIND_TURN_END,
                        "payload": {"finish_reason": finish.value},
                        "ts": None,
                    },
                )

        with contextlib.suppress(Exception):
            from agentcore.conversation.store import get_cloud_store

            await get_cloud_store().clear_stream_segments(turn_id=message_id)

        # Durable incomplete chrome is committed; stamp payroll next (best-effort).
        with contextlib.suppress(Exception):
            await _reconcile_interrupted_turn_cost(
                message_id=message_id,
                conversation_id=conversation_id,
                trace_id=resolved_trace,
            )

        logger.info(
            "turn.interrupt_closed",
            message_id=message_id,
            conversation_id=conversation_id,
            reason=resolved.value,
            finish_reason=finish.value,
            skipped_upsert=skip_upsert,
        )
        return True
    except Exception as e:  # noqa: BLE001 — caller decides lease retention
        logger.warning(
            "turn.interrupt_close_failed",
            message_id=message_id,
            conversation_id=conversation_id,
            reason=str(resolved),
            error=str(e),
        )
        return False
