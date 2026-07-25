"""Cloud ConversationStore — Postgres-backed turn-authority persistence."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError

from agentcore.billing.gate import resolve_and_gate_background
from agentcore.config import settings
from agentcore.conversation.common import generate_followups as mint_followups
from agentcore.conversation.common import generate_title as mint_title
from agentcore.conversation.common import log_cost_recorded
from agentcore.conversation.compaction import schedule_compaction
from agentcore.conversation.store.merge import (
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INCOMPLETE,
    MESSAGE_STATUS_RUNNING,
    merge_usage_status,
    pick_merged_content,
)
from agentcore.conversation.turn_stats import turn_worker_stats
from agentcore.core.error_codes import ErrorCode
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory, telemetry_session_factory
from agentcore.db.repositories import (
    ConversationRepository,
    MessageRepository,
    TurnJournalRepository,
    TurnMetricsRepository,
    TurnStreamStateRepository,
)
from agentcore.llm.factory import build_provider
from agentcore.llm.resolve import LLMCredentials
from agentcore.llm.resolve import resolve_turn_model as resolve_user_model
from agentcore.memory.consolidation import schedule_consolidation
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    followups_generated,
)
from agentcore.runtime.journal import journal_entries_from_display_runs, persist_turn_journal
from agentcore.workspace.protocol import WorkspaceBackend
from agentcore.workspace.snapshots import create_snapshot

logger = get_logger(__name__)

_RUN_ERROR_MESSAGE_CAP = 2000
_SKIP_DERIVED_FINISH = frozenset(
    {
        FinishReason.PAUSED.value,
        FinishReason.ERROR.value,
        FinishReason.CANCELLED.value,
    }
)


def _incomplete_body(content: str) -> str:
    """Streamed captain text only; interrupt chrome is metadata + UI, not body copy."""
    return (content or "").strip()


def _usage_metadata(
    result: dict,
    *,
    status: str,
    extra: dict | None = None,
) -> dict:
    meta = {
        "status": status,
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
        "reasoning_tokens": result.get("reasoning_tokens", 0),
        "cache_hit_tokens": result.get("cache_hit_tokens", 0),
        "cache_miss_tokens": result.get("cache_miss_tokens", 0),
        "rounds": result.get("rounds", 0),
    }
    finish = result.get("finish_reason")
    finish_value = getattr(finish, "value", finish)
    if finish_value is not None:
        meta["finish_reason"] = finish_value
    error_code = result.get("error_code")
    if error_code:
        meta["error_code"] = error_code
    collab = result.get("collab")
    if collab:
        meta["collab"] = collab
    if extra:
        meta.update(extra)
    return meta


class CloudStore:
    """Postgres ConversationStore (收编 placeholder / checkpoint / journal / finalize / salvage)."""

    async def begin_turn(
        self,
        *,
        conversation_id: str,
        message_id: str,
        trace_id: str,
    ) -> None:
        """Create the running assistant row at turn start (progressive persistence).

        Failures propagate: a turn must not run SSE / pipeline without a durable
        assistant row. Finalize only settles that row (content / error / status) —
        it is not a create-on-failure fallback.
        """
        try:
            async with async_session_factory() as session:
                await MessageRepository(session).create_assistant_placeholder(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    trace_id=trace_id,
                )
        except Exception as e:
            logger.error(
                "chat.assistant_placeholder_failed",
                conversation_id=conversation_id,
                message_id=message_id,
                error=str(e),
            )
            raise

    async def checkpoint(
        self,
        *,
        conversation_id: str,
        message_id: str,
        content: str,
    ) -> None:
        """Progressive content flush with D7 monotonic + status-gate rules."""
        async with async_session_factory() as session:
            await MessageRepository(session).update_assistant_content(
                conversation_id=conversation_id,
                message_id=message_id,
                content=content,
            )

    async def append_journal(
        self,
        *,
        turn_id: str,
        seq: int | None,
        conversation_id: str,
        trace_id: str | None,
        entry: dict[str, Any],
    ) -> int | None:
        """Append-on-emit journal fact via the telemetry pool (no primary-pool contention).

        ``seq=None`` ⇒ DB 原子分配（live）；``seq=int`` ⇒ merge 幂等去重（outbox 回写）。
        Returns the durable seq on insert, or ``None`` on merge duplicate no-op.
        """
        from agentcore.runtime.audit.hooks import on_journal_fact_appended

        async with telemetry_session_factory() as db:
            allocated = await TurnJournalRepository(db).append(
                turn_id=turn_id,
                seq=seq,
                conversation_id=conversation_id,
                trace_id=trace_id,
                entry=entry,
            )
        if allocated is not None:
            on_journal_fact_appended(entry)
        return allocated

    async def finalize(
        self,
        *,
        mode: Literal["cloud", "local"] = "cloud",
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if mode == "local":
            return await self._finalize_local(**kwargs)
        await self._finalize_cloud(**kwargs)
        return None

    async def salvage(
        self,
        *,
        journal: list[dict[str, Any]],
        content: str,
        conversation_id: str,
        trace_id: str,
        message_id: str | None,
    ) -> None:
        """Persist a cancelled turn's already-streamed reply + finished work."""
        streamed = (content or "").strip()
        body = streamed
        if not message_id:
            logger.warning(
                "chat.incomplete_persist_skipped",
                conversation_id=conversation_id,
                reason="no_message_id",
            )
            return
        try:
            async with async_session_factory() as session:
                await MessageRepository(session).upsert_assistant(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    content=body,
                    trace_id=trace_id,
                    metadata={
                        "status": MESSAGE_STATUS_INCOMPLETE,
                        "incomplete": True,
                        "finish_reason": FinishReason.CANCELLED.value,
                    },
                    merge=True,
                )
                await persist_turn_journal(
                    session,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    entries=journal_entries_from_display_runs(
                        {
                            "events": journal,
                            "finish_reason": FinishReason.CANCELLED.value,
                        }
                    ),
                )
            # 时序不变量: terminal snapshot landed → drop in-flight segments.
            with contextlib.suppress(Exception):
                await self.clear_stream_segments(turn_id=message_id)
            logger.info(
                "chat.incomplete_persisted",
                conversation_id=conversation_id,
                events=len(journal),
                content_chars=len(streamed),
            )
        except Exception as e:
            logger.warning(
                "chat.incomplete_persist_failed",
                conversation_id=conversation_id,
                error=str(e),
            )

    async def upsert_stream_segments(
        self,
        *,
        turn_id: str,
        segments: Sequence[tuple[str, str, int]],
    ) -> None:
        if not segments:
            return
        async with async_session_factory() as session:
            await TurnStreamStateRepository(session).upsert_many(
                turn_id=turn_id,
                segments=segments,
            )

    async def list_stream_segments(
        self,
        *,
        turn_id: str,
    ) -> list[dict[str, Any]]:
        async with async_session_factory() as session:
            rows = await TurnStreamStateRepository(session).list_for_turn(turn_id)
        return [
            {"channel": r.channel, "text": r.text, "generation": r.generation} for r in rows
        ]

    async def list_stream_segments_map(
        self,
        *,
        turn_ids: Sequence[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not turn_ids:
            return {}
        async with async_session_factory() as session:
            by_turn = await TurnStreamStateRepository(session).list_for_turns(turn_ids)
        return {
            tid: [
                {"channel": r.channel, "text": r.text, "generation": r.generation} for r in rows
            ]
            for tid, rows in by_turn.items()
        }

    async def clear_stream_segments(
        self,
        *,
        turn_id: str,
    ) -> None:
        async with async_session_factory() as session:
            await TurnStreamStateRepository(session).delete_for_turn(turn_id)

    async def _finalize_cloud(
        self,
        *,
        result: dict,
        conversation_id: str,
        user_id: str,
        folder_id: str | None,
        backend: WorkspaceBackend,
        sink: EventSink,
        user_message: str,
        llm_credentials: LLMCredentials | None,
        trace_id: str,
        turn_id: str,
        duration_ms: int,
        kind: str = "turn",
    ) -> None:
        """Cloud end-of-turn: assistant row + journal + ledger + telemetry + derived."""
        assistant_reply = result.get("content") or ""
        assistant_reasoning = result.get("reasoning_content") or None
        assistant_citations = result.get("citations") or None
        assistant_evidence_ledger = result.get("evidence_ledger") or None
        journal_entries = result.get("journal_entries")
        cost_runs = result.get("cost_runs") or []

        finish = result.get("finish_reason")
        finish_value = getattr(finish, "value", finish)
        if finish_value == FinishReason.PAUSED.value:
            logger.info(
                "chat.turn_paused",
                conversation_id=conversation_id,
                message_id=result.get("message_id"),
            )
            message_id = result.get("message_id")
            if message_id:
                try:
                    async with async_session_factory() as session:
                        await MessageRepository(session).upsert_assistant(
                            conversation_id=conversation_id,
                            message_id=message_id,
                            content=assistant_reply,
                            reasoning_content=assistant_reasoning,
                            citations=assistant_citations,
                            evidence_ledger=assistant_evidence_ledger,
                            trace_id=trace_id,
                            metadata=_usage_metadata(
                                result,
                                status=MESSAGE_STATUS_RUNNING,
                                extra={"paused": True},
                            ),
                            merge=True,
                        )
                    # 时序不变量: pause snapshot landed → drop segments (paused 列优先).
                    with contextlib.suppress(Exception):
                        await self.clear_stream_segments(turn_id=message_id)
                except Exception as e:
                    logger.warning(
                        "chat.pause_snapshot_failed",
                        conversation_id=conversation_id,
                        message_id=message_id,
                        error=str(e),
                    )
            return

        turn_error = result.get("error")
        run_error = (
            {
                "code": result.get("error_code") or ErrorCode.PIPELINE_ERROR,
                "message": str(turn_error)[:_RUN_ERROR_MESSAGE_CAP],
            }
            if turn_error
            else None
        )
        abnormal = bool(turn_error) or (
            finish_value is not None and finish_value != FinishReason.END_TURN.value
        )
        synth_entries = (
            journal_entries_from_display_runs(
                {"finish_reason": finish_value, "error": run_error}
            )
            if journal_entries is None and abnormal
            else None
        )
        durable_entries = journal_entries if journal_entries is not None else synth_entries
        message_id = result.get("message_id")
        terminal_status = (
            MESSAGE_STATUS_FAILED
            if turn_error or finish_value == FinishReason.ERROR.value
            else MESSAGE_STATUS_COMPLETE
        )

        async with async_session_factory() as session:
            msg_repo = MessageRepository(session)

            if message_id:
                await msg_repo.upsert_assistant(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    content=assistant_reply,
                    reasoning_content=assistant_reasoning,
                    citations=assistant_citations,
                    evidence_ledger=assistant_evidence_ledger,
                    trace_id=trace_id,
                    metadata=_usage_metadata(result, status=terminal_status),
                    merge=True,
                )
                if durable_entries is not None:
                    await persist_turn_journal(
                        session,
                        message_id=message_id,
                        conversation_id=conversation_id,
                        trace_id=trace_id,
                        entries=durable_entries,
                    )

            # Reconcile even when in-memory cost_runs is thin: cost_calls (call meter)
            # is authority for captain+worker spend; orphans (vision) still fold from cost_runs.
            if cost_runs or message_id:
                try:
                    from agentcore.billing.turn_ledger import reconcile_turn_cost_ledger
                    from agentcore.runtime.costing import aggregate_cost

                    ledger_rows = await reconcile_turn_cost_ledger(
                        session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=result.get("message_id"),
                        cost_runs=list(cost_runs),
                        trace_id=trace_id,
                    )
                    if ledger_rows:
                        log_cost_recorded(
                            conversation_id, result.get("message_id"), ledger_rows
                        )
                except Exception as e:
                    await session.rollback()
                    logger.warning(
                        "cost.ledger_write_failed",
                        conversation_id=conversation_id,
                        message_id=result.get("message_id"),
                        error=str(e),
                    )
                    from agentcore.billing.cost_ledger_queue import get_cost_ledger_queue

                    if cost_runs:
                        get_cost_ledger_queue().enqueue_runs(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message_id=result.get("message_id"),
                            runs=list(cost_runs),
                            trace_id=trace_id,
                            source="turn",
                        )
                else:
                    # P2 DERIVED: stamp turn total onto messages.cost (footer reload).
                    # Best-effort sibling of the ledger write — failure must not undo ledger.
                    if message_id and ledger_rows:
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
                            )

            delegated, workers = turn_worker_stats(result)
            collab = result.get("collab") or {}
            try:
                await TurnMetricsRepository(session).record(
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    agent_id="CEO",
                    kind=kind,
                    status=(
                        "error"
                        if turn_error or finish_value == FinishReason.ERROR.value
                        else "ok"
                    ),
                    finish_reason=finish_value,
                    error=str(turn_error)[:1000] if turn_error else None,
                    rounds=int(result.get("rounds", 0) or 0),
                    duration_ms=duration_ms,
                    delegated=delegated,
                    workers=workers,
                    input_tokens=int(result.get("input_tokens", 0) or 0),
                    output_tokens=int(result.get("output_tokens", 0) or 0),
                    boundary_yields=int(collab.get("boundary_yields", 0) or 0),
                    scope_signals=int(collab.get("scope_signals", 0) or 0),
                    revises=int(collab.get("revises", 0) or 0),
                    escalations=int(collab.get("escalations", 0) or 0),
                    audit_drops=int(result.get("audit_drops", 0) or 0),
                )
            except Exception as e:
                await session.rollback()
                logger.warning(
                    "observability.turn_metrics_write_failed",
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    error=str(e),
                )

        # 时序不变量: terminal snapshot (above) landed → drop in-flight segments.
        if message_id:
            with contextlib.suppress(Exception):
                await self.clear_stream_segments(turn_id=message_id)

        # Demo-tape fidelity: player puts recorded chips on result["followups"].
        # Non-empty → persist + emit with *this* turn's message_id; skip LLM mint.
        # Absent / empty → unchanged live mint path (mutually exclusive).
        tape_followups = result.get("followups")
        if isinstance(tape_followups, list):
            tape_followups = [str(x) for x in tape_followups if str(x).strip()]
        else:
            tape_followups = []

        wants_followups = (
            finish_value == FinishReason.END_TURN.value and bool(assistant_reply.strip())
        )

        if tape_followups and message_id:
            async with async_session_factory() as session:
                await MessageRepository(session).set_followups(
                    message_id,
                    conversation_id=conversation_id,
                    followups=tape_followups,
                )
            sink.emit(
                followups_generated(
                    tape_followups,
                    conversation_id=conversation_id,
                    message_id=message_id,
                )
            )
        elif wants_followups:
            from agentcore.memory.followups import select_motion_card_from_journal
            from agentcore.runtime.kickoff.stage_card import emit_stage_card_for_motion

            # Worker debriefs (run_completed / run_failed) already ride journal_entries;
            # last compliant motion_card → 阶段推进卡（批 B）；停发确定性「开辩」followup 芯片。
            journal_entries = result.get("journal_entries")
            motion_card = select_motion_card_from_journal(journal_entries)
            stage_emitted = False
            if isinstance(motion_card, dict) and message_id:
                stage_emitted = (
                    await emit_stage_card_for_motion(
                        sink,
                        conversation_id=conversation_id,
                        motion_card=motion_card,
                        turn_id=str(message_id),
                        journal_entries=(
                            journal_entries if isinstance(journal_entries, list) else None
                        ),
                    )
                ) is not None
            provider = None
            model: str | None = None
            try:
                async with async_session_factory() as session:
                    bg_credentials = await resolve_and_gate_background(
                        session, user_id, purpose="followups"
                    )
                if bg_credentials is None:
                    raise RuntimeError("background credentials unavailable")
                model = resolve_user_model(bg_credentials)
                provider = build_provider(bg_credentials, purpose="platform_internal")
            except Exception as e:
                logger.warning(
                    "chat.followups_provider_unavailable",
                    conversation_id=conversation_id,
                    error=str(e),
                )
            try:
                followups = await mint_followups(
                    provider=provider,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                    model=model,
                    # 有推进卡时不再注入开辩芯片（卡即芯片）。
                    motion_card=None if stage_emitted else motion_card,
                )
                message_id = result.get("message_id")
                if followups and message_id:
                    async with async_session_factory() as session:
                        await MessageRepository(session).set_followups(
                            message_id,
                            conversation_id=conversation_id,
                            followups=followups,
                        )
                    sink.emit(
                        followups_generated(
                            followups,
                            conversation_id=conversation_id,
                            message_id=message_id,
                        )
                    )
            finally:
                if provider is not None:
                    await provider.close()

        schedule_consolidation(conversation_id)
        schedule_compaction(conversation_id, result.get("input_tokens", 0))

        if (
            settings.workspace_snapshot_enabled
            and backend.location == "server"
            and getattr(backend, "dirty", False)
        ):
            try:
                ref = await create_snapshot(
                    user_id=user_id,
                    folder_id=None,
                    conversation_id=conversation_id,
                )
                logger.info(
                    "workspace.snapshot_created",
                    conversation_id=conversation_id,
                    snapshot_id=ref.snapshot_id,
                    size_bytes=ref.size_bytes,
                )
            except Exception as e:
                logger.warning(
                    "workspace.snapshot_failed",
                    conversation_id=conversation_id,
                    error=str(e),
                )

    async def _finalize_local(
        self,
        *,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_content: str,
        assistant_reasoning: str | None = None,
        citations: list[dict] | None = None,
        evidence_ledger: list[dict] | None = None,
        runs: dict | None = None,
        journal: list[dict] | None = None,
        user_message_id: str,
        message_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_hit_tokens: int = 0,
        cache_miss_tokens: int = 0,
        rounds: int = 0,
        trace_id: str,
        finish_reason: str | None = None,
        llm_credentials: LLMCredentials | None = None,
    ) -> dict[str, Any]:
        """Local write-back via finalize(mode=local): content + status + journal."""
        finish_value = finish_reason
        is_paused = finish_value == FinishReason.PAUSED.value
        is_incomplete = finish_value == FinishReason.CANCELLED.value
        skip_derived = finish_value in _SKIP_DERIVED_FINISH

        async with async_session_factory() as session:
            msg_repo = MessageRepository(session)
            existing_user = await msg_repo.get_by_id(
                user_message_id, conversation_id=conversation_id
            )
            existing_assistant = (
                await msg_repo.get_by_id(message_id, conversation_id=conversation_id)
                if message_id
                else None
            )

        turn_user = existing_user
        if turn_user is None and existing_assistant is not None and message_id:
            async with async_session_factory() as session:
                turn_user = await MessageRepository(session).user_message_for_assistant(
                    conversation_id=conversation_id,
                    assistant_message_id=message_id,
                )
            if turn_user is not None:
                logger.info(
                    "chat.local_turn_reuse_paired_user",
                    conversation_id=conversation_id,
                    message_id=message_id,
                    user_message_id=turn_user.id,
                )

        user_msg_id = turn_user.id if turn_user is not None else user_message_id
        if turn_user is None:
            try:
                async with async_session_factory() as session:
                    user_msg = await MessageRepository(session).create(
                        conversation_id=conversation_id,
                        role="user",
                        content=user_message,
                        message_id=user_message_id,
                    )
                    user_msg_id = user_msg.id
            except IntegrityError:
                logger.info(
                    "chat.local_turn_idempotent_race",
                    conversation_id=conversation_id,
                    message_id=message_id,
                )
                user_msg_id = user_message_id

        assistant_message_id: str | None = None
        if is_paused:
            terminal_status = MESSAGE_STATUS_RUNNING
        elif is_incomplete:
            terminal_status = MESSAGE_STATUS_INCOMPLETE
        elif finish_value == FinishReason.ERROR.value:
            terminal_status = MESSAGE_STATUS_FAILED
        else:
            terminal_status = MESSAGE_STATUS_COMPLETE

        content_to_write = (
            _incomplete_body(assistant_content) if is_incomplete else assistant_content
        )

        usage_metadata: dict[str, Any] = {
            "status": terminal_status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "cache_miss_tokens": cache_miss_tokens,
            "rounds": rounds,
        }
        if is_paused:
            usage_metadata["paused"] = True
        elif is_incomplete:
            usage_metadata["incomplete"] = True
            usage_metadata["finish_reason"] = FinishReason.CANCELLED.value
        elif finish_value is not None:
            usage_metadata["finish_reason"] = finish_value
        run_error = runs.get("error") if isinstance(runs, dict) else None
        if isinstance(run_error, dict):
            err_code = run_error.get("code")
            if err_code:
                usage_metadata["error_code"] = err_code

        # Settle whenever the turn has a terminal/pause surface — including empty
        # ERROR (soft-fail / first-turn crash) and empty bubble with process state
        # (runs/journal — aligns with cloud live: process projection must land).
        # True no-op (no orphan row): empty body AND no process state AND not
        # paused/incomplete/failed. Desktop deletes outbox only on assistant id or noop.
        has_process_state = bool(
            (isinstance(runs, dict) and bool(runs))
            or (isinstance(journal, list) and len(journal) > 0)
        )
        should_settle = bool(
            message_id
            and (
                content_to_write
                or is_paused
                or is_incomplete
                or terminal_status == MESSAGE_STATUS_FAILED
                or has_process_state
            )
        )
        # Intentional skip — client may delete outbox; never a silent "200 + null id".
        noop = bool(message_id) and not should_settle
        if should_settle:
            async with async_session_factory() as session:
                # D7: idempotent merge upsert (no early-return when rows already exist).
                existing = await MessageRepository(session).get_by_id(
                    message_id, conversation_id=conversation_id
                )
                existing_usage = (existing.usage if existing else None) or {}
                merged_usage = merge_usage_status(existing_usage, usage_metadata)
                content = pick_merged_content(
                    existing.content if existing else None,
                    content_to_write,
                    incoming_status=terminal_status,
                )
                assistant_msg = await MessageRepository(session).upsert_assistant(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    content=content,
                    reasoning_content=assistant_reasoning,
                    citations=citations,
                    evidence_ledger=evidence_ledger,
                    trace_id=trace_id,
                    metadata=merged_usage,
                    merge=True,
                )
                assistant_message_id = assistant_msg.id
                if not is_paused:
                    # Happy path: project display ``runs``. Crash salvage: raw journal facts.
                    if runs is not None:
                        durable = journal_entries_from_display_runs(runs)
                    elif journal:
                        durable = journal
                    else:
                        durable = None
                    if durable is not None:
                        await persist_turn_journal(
                            session,
                            message_id=assistant_msg.id,
                            conversation_id=conversation_id,
                            trace_id=trace_id,
                            entries=durable,
                        )
            # 时序不变量: local terminal/pause snapshot landed → drop segments.
            with contextlib.suppress(Exception):
                await self.clear_stream_segments(turn_id=message_id)

        if skip_derived:
            logger.info(
                "chat.local_turn_recorded",
                conversation_id=conversation_id,
                message_id=message_id,
                finish_reason=finish_value,
                chars=len(content_to_write or ""),
                rounds=rounds,
            )
            return {
                "user_message_id": user_msg_id,
                "assistant_message_id": assistant_message_id,
                "title": None,
                "followups": None,
                "noop": noop,
            }

        async with async_session_factory() as session:
            conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
            needs_title = bool(conv and not conv.title)
            existing_title = conv.title if conv else None

        title: str | None = existing_title
        minted_followups: list[str] | None = None
        wants_followups = (
            finish_value == FinishReason.END_TURN.value
            and bool((assistant_content or "").strip())
            and bool(assistant_message_id)
        )
        if needs_title or wants_followups:
            from agentcore.memory.followups import select_motion_card_from_journal
            from agentcore.runtime.kickoff.stage_card import emit_stage_card_for_motion

            motion_card = None
            stage_emitted = False
            if wants_followups:
                journal_src = journal
                if journal_src is None and isinstance(runs, dict):
                    events = runs.get("events")
                    journal_src = events if isinstance(events, list) else None
                motion_card = select_motion_card_from_journal(journal_src)
                if isinstance(motion_card, dict) and assistant_message_id:
                    # Local write-back has no live SSE sink; journal via
                    # prewrite_settlement_direct still lands the durable card.
                    stage_emitted = (
                        await emit_stage_card_for_motion(
                            None,
                            conversation_id=conversation_id,
                            motion_card=motion_card,
                            turn_id=str(assistant_message_id),
                            journal_entries=(
                                journal_src if isinstance(journal_src, list) else None
                            ),
                        )
                    ) is not None
            provider = None
            model: str | None = None
            try:
                async with async_session_factory() as session:
                    bg_credentials = await resolve_and_gate_background(
                        session, user_id, purpose="title" if needs_title else "followups"
                    )
                if bg_credentials is None:
                    raise RuntimeError("background credentials unavailable")
                model = resolve_user_model(bg_credentials)
                provider = build_provider(bg_credentials, purpose="platform_internal")
            except Exception as e:
                logger.warning(
                    "chat.local_derived_provider_unavailable",
                    conversation_id=conversation_id,
                    error=str(e),
                )
            try:
                if needs_title and provider is not None:
                    minted = await mint_title(
                        provider=provider,
                        conversation_id=conversation_id,
                        user_message=user_message,
                        assistant_reply=assistant_content,
                        model=model,
                    )
                    title = minted.title
                    if title:
                        async with async_session_factory() as session:
                            await ConversationRepository(session).update_title_unscoped(
                                conversation_id, title
                            )
                if wants_followups and provider is not None:
                    followups = await mint_followups(
                        provider=provider,
                        conversation_id=conversation_id,
                        user_message=user_message,
                        assistant_reply=assistant_content,
                        model=model,
                        motion_card=None if stage_emitted else motion_card,
                    )
                    if followups and assistant_message_id:
                        async with async_session_factory() as session:
                            await MessageRepository(session).set_followups(
                                assistant_message_id,
                                conversation_id=conversation_id,
                                followups=followups,
                            )
                        minted_followups = followups
            finally:
                if provider is not None:
                    await provider.close()

        schedule_consolidation(conversation_id)

        logger.info(
            "chat.local_turn_recorded",
            conversation_id=conversation_id,
            message_id=message_id,
            chars=len(assistant_content or ""),
            rounds=rounds,
        )
        return {
            "user_message_id": user_msg_id,
            "assistant_message_id": assistant_message_id,
            "title": title,
            "followups": minted_followups,
            "noop": noop,
        }


_cloud_store: CloudStore | None = None


def get_cloud_store() -> CloudStore:
    """Process-wide CloudStore singleton (host + /local-turns share one impl)."""
    global _cloud_store
    if _cloud_store is None:
        _cloud_store = CloudStore()
    return _cloud_store
