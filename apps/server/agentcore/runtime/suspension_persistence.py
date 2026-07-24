"""DB-backed save / claim / delete / restore for paused turns (结构化挂起 2b turn 级落盘).

Bridges the DB-unaware ``delegate`` checkpoint hook + the resume entry point to the
``paused_turns`` table. The pipeline wires :func:`save_paused_turn` / :func:`delete_paused_turn`
into ``delegate`` (persist a frame before the wait; drop it after a live in-process
resolve), and ``resume_chat`` calls :func:`claim_paused_turn` (atomic read-and-delete,
so a turn is never resumed twice) + :func:`list_paused_turns` (a conversation's pending
frames on reopen). On cloud resume failure, :func:`restore_paused_turn` re-upserts the
claimed frame (sidecar ``rollback_claim`` parity) so the user can retry. Uses
``async_session_factory`` directly (not an injected request session), matching the
cost-ledger / session-roster persistence posture.

The paused turn's journal-so-far rides the ``turn_journal`` table (唯一事实源, §8.3),
NOT the frame. Facts are normally appended on emit during the turn; at pause time
:func:`save_paused_turn` also snapshots the suspending face's ``journal_entries`` (the
authoritative fact-log stream, incl. the trailing ``*_required`` card) into
``turn_journal`` so a cold resume can rebuild the CEO window even when the append-on-emit
writer lagged or degraded. :func:`claim_paused_turn` re-hydrates from that table.

D11: save failures raise (no silent degrade). Claim competition → ``None`` (route 404);
claim-then-hydrate failure restores the frame and raises (route 5xx, retryable).
"""

from __future__ import annotations

from typing import Any

from agentcore.core.log_context import get_log_value
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import PausedTurnRepository, TurnJournalRepository
from agentcore.push import PushNotification, notify_user
from agentcore.runtime.journal.writer import current_journal_writer
from agentcore.runtime.suspension import (
    SuspensionKind,
    TurnSuspension,
    suspension_from_json,
)

logger = get_logger(__name__)


async def save_paused_turn(suspension: TurnSuspension) -> None:
    """Persist one paused-turn frame, keyed by its ``message_id``.

    Stamps the ambient turn ``trace_id`` (this runs inside the pipeline's trace
    scope) so the persisted pause links back to its originating turn's logs.
    Upsert: re-pausing the same turn (resume → pause again) overwrites in place.
    The journal-so-far is NOT in the frame — it is written to ``turn_journal`` here
    (唯一事实源, §8.3) from the suspending face's ``journal_entries`` snapshot.
    Raises on persistence failure (D11 — no fake saved).
    """
    trace_id = suspension.trace_id or get_log_value("trace_id") or None
    writer = current_journal_writer.get()
    if writer is not None:
        await writer.flush()
        if writer.degraded:
            suspension.journal_degraded = True
    journal_entries = list(suspension.journal_entries or [])
    try:
        async with async_session_factory() as db:
            if journal_entries:
                await TurnJournalRepository(db).record(
                    turn_id=suspension.message_id,
                    conversation_id=suspension.conversation_id,
                    trace_id=trace_id,
                    entries=journal_entries,
                )
            await PausedTurnRepository(db).upsert(
                message_id=suspension.message_id,
                conversation_id=suspension.conversation_id,
                user_id=suspension.user_id,
                frame=suspension.to_json(),
                trace_id=trace_id,
            )
    except Exception as e:
        # D11：saver 失败必须如实暴露（假 saved 缝）——不再吞异常报 saved=True。
        logger.warning(
            "suspension.persist_failed",
            message_id=suspension.message_id,
            error=str(e),
        )
        raise
    # Hard boundary: after the durable snapshot is the canonical journal, seal the
    # append-on-emit writer so post-save emits (trailing *_required, suspending
    # tool_use_end) cannot diverge DB rows from the paused snapshot.
    if writer is not None:
        await writer.seal()
    # A durable pause is the canonical 需要你 (attention) event: the turn is now BLOCKED
    # on the user and stays so until they act. Fan a native push out to their devices so
    # they learn even with the app backgrounded (SSE gone). Best-effort + default-off
    # (notify_user short-circuits when push is unconfigured) — never blocks the pause.
    await _notify_pause(suspension)


async def _notify_pause(suspension: TurnSuspension) -> None:
    """Push a 需要你 notification for a durable pause (best-effort, default-off).

    Copy is keyed by the suspend kind; the ``data`` carries the ids the mobile client
    deep-links on tap (conversation + the paused turn). ``notify_user`` itself swallows
    all errors, so this never affects the pause.
    """
    if suspension.kind == SuspensionKind.PLAN_REVIEW:
        title = "AI 计划待确认"
        body = "团队已产出阶段成果，待你确认是否继续。"
    else:
        title = "AI 需要你的回应"
        question = (getattr(suspension, "question", "") or "").strip()
        body = question[:120] if question else "AI 正在等待你的回应以继续任务。"
    await notify_user(
        suspension.user_id,
        PushNotification(
            title=title,
            body=body,
            data={
                "conversation_id": suspension.conversation_id,
                "message_id": suspension.message_id,
                "kind": suspension.kind.value,
            },
        ),
    )


async def delete_paused_turn(message_id: str) -> None:
    """Drop a paused-turn frame (a live in-process resolve / timeout settled it).

    Best-effort: a stale frame left by a failed delete is harmless — ``claim`` would
    only resurrect a turn the user can re-decide, and the next live resolve overwrites
    it. NEVER raises into the turn.
    """
    try:
        async with async_session_factory() as db:
            await PausedTurnRepository(db).delete(message_id)
    except Exception as e:  # noqa: BLE001 — cleanup must never break the turn
        logger.warning("suspension.delete_failed", message_id=message_id, error=str(e))


async def _upsert_paused_frame(
    *,
    message_id: str,
    conversation_id: str,
    user_id: str,
    frame: dict[str, Any],
    trace_id: str | None,
) -> None:
    """Re-upsert a raw paused frame (restore / claim-hydrate rollback). Best-effort."""
    try:
        async with async_session_factory() as db:
            await PausedTurnRepository(db).upsert(
                message_id=message_id,
                conversation_id=conversation_id,
                user_id=user_id,
                frame=frame,
                trace_id=trace_id,
            )
    except Exception as e:  # noqa: BLE001 — restore must never break the error path
        logger.warning(
            "suspension.restore_failed",
            message_id=message_id,
            error=str(e),
        )


async def restore_paused_turn(suspension: TurnSuspension) -> None:
    """Re-upsert a claimed frame after a failed cloud resume so the user can retry.

    ``claim`` is DELETE ... RETURNING — on resume failure the in-memory
    :class:`TurnSuspension` and the ``turn_journal`` rows still exist, but the
    ``paused_turns`` row is gone. This puts the frame back (sidecar's
    ``rollback_claim`` parity for the cloud path). Does NOT re-push (the user
    already got the original pause notification) and does NOT rewrite
    ``turn_journal`` (claim left those rows in place). Best-effort; never raises.
    """
    await _upsert_paused_frame(
        message_id=suspension.message_id,
        conversation_id=suspension.conversation_id,
        user_id=suspension.user_id,
        frame=suspension.to_json(),
        trace_id=suspension.trace_id,
    )


async def load_paused_turn(
    message_id: str, *, conversation_id: str | None = None
) -> TurnSuspension | None:
    """Read a paused turn without claiming (D8 cold-path peek before settlement prewrite).

    Does not touch ``turn_journal`` — the subsequent :func:`claim_paused_turn` re-hydrates
    entries (including any settlement prewritten between peek and claim). ``None`` when
    absent / wrong conversation / unreadable.
    """
    try:
        async with async_session_factory() as db:
            row = await PausedTurnRepository(db).get(message_id)
            if row is None:
                return None
            if conversation_id is not None and row.conversation_id != conversation_id:
                return None
            return suspension_from_json(row.frame)
    except Exception as e:  # noqa: BLE001 — peek failure reads as "not resumable"
        logger.warning("suspension.load_failed", message_id=message_id, error=str(e))
        return None


async def claim_paused_turn(
    message_id: str, *, conversation_id: str | None = None
) -> TurnSuspension | None:
    """Atomically read-and-delete a paused turn for resume; ``None`` if already
    claimed / absent.

    The atomic claim (DELETE ... RETURNING) means two racing ``/resume`` calls can't
    both continue the same turn — the loser gets ``None`` (→ 404 at the route). Pass
    ``conversation_id`` (the one the route verified the caller owns) so a frame is only
    claimed within that conversation (IDOR-safe).

    Claim competition / missing row → ``None``. After a successful claim, frame parse
    or journal load failure restores the row and **raises** (route 5xx, frame kept for
    retry) — never silently drop a claimed frame.

    The journal-so-far is re-hydrated from ``turn_journal`` (唯一事实源, it is not in the
    frame) onto :attr:`TurnSuspension.journal_entries` (the §8.3 fact-log stream, incl. the
    execution facts the display projection drops): the resume folds it via ``window_from_journal``
    to rebuild the captain window (执行级事件溯源 Phase 2 ④/⑤ — the window is a projection of the
    journal, no longer read from a frame ``transcript`` blob, which is no longer serialized).
    The display ``journal`` resume seed is a DERIVED property of those entries (P0-B Phase 3),
    so it seeds identically to the Sidecar. The window's prior-turn history is reloaded
    separately from the message DB by the caller (``service.resume_chat``) and threaded in. The
    stored rows are left in place: the resumed turn re-records them wholesale on completion (or
    the TTL sweep clears them if the turn is abandoned).
    """
    claimed: dict[str, Any] | None = None
    try:
        async with async_session_factory() as db:
            row = await PausedTurnRepository(db).claim(message_id, conversation_id=conversation_id)
            if row is None:
                return None
            # Materialize before the session closes (expire_on_commit).
            claimed = {
                "message_id": row.message_id,
                "conversation_id": row.conversation_id,
                "user_id": row.user_id,
                "frame": dict(row.frame) if isinstance(row.frame, dict) else row.frame,
                "trace_id": row.trace_id,
            }
    except Exception as e:  # noqa: BLE001 — claim competition / DB fault → not resumable
        logger.warning("suspension.claim_failed", message_id=message_id, error=str(e))
        return None

    assert claimed is not None
    try:
        async with async_session_factory() as db:
            entries = await TurnJournalRepository(db).load(message_id)
        suspension = suspension_from_json(claimed["frame"])
        suspension.journal_entries = list(entries or [])
    except Exception as e:
        logger.error(
            "suspension.claim_hydrate_failed",
            message_id=message_id,
            error=str(e),
        )
        await _upsert_paused_frame(
            message_id=claimed["message_id"],
            conversation_id=claimed["conversation_id"],
            user_id=claimed["user_id"],
            frame=claimed["frame"],
            trace_id=claimed["trace_id"],
        )
        raise

    if suspension.journal_degraded and not suspension.journal_entries:
        logger.warning(
            "suspension.claim_journal_degraded",
            message_id=message_id,
        )
    return suspension


async def list_paused_turns(conversation_id: str) -> list[TurnSuspension]:
    """A conversation's pending paused turns (oldest first), for reopen-time hydration.

    Read-only (does not claim); the resume call claims. Best-effort: an error yields an
    empty list so reopening a conversation never fails on a paused-turn lookup.
    """
    try:
        async with async_session_factory() as db:
            rows = await PausedTurnRepository(db).list_pending(conversation_id)
    except Exception as e:  # noqa: BLE001 — a list failure degrades to "none pending"
        logger.warning("suspension.list_failed", conversation_id=conversation_id, error=str(e))
        return []
    return [suspension_from_json(r.frame) for r in rows]
