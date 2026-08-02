"""Sidecar turn execution: run, resume, event pump + outbox finalize."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from agentcore.core.log_context import log_context
from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.llm.resolve import resolve_turn_model
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.events import EventSink, FinishReason, message_end
from agentcore.runtime.journal import runs_from_entries
from agentcore.runtime.suspension import TurnSuspension
from agentcore.sidecar import protocol
from agentcore.sidecar.server_pkg.result import trim_result

logger = get_logger(__name__)


def _finish_str(result: dict[str, Any]) -> str | None:
    finish = result.get("finish_reason")
    if finish is None:
        return None
    return finish.value if hasattr(finish, "value") else str(finish)


def _emit_user_stop_message_end(sink: EventSink) -> None:
    """Live stop confirmation for the UI (honest ``stopping`` → ``stopped``).

    Must run before ``sink.close()`` so the event pump still drains it. JSON-RPC
    ``TURN_CANCELLED`` alone is not enough — the renderer confirms on ``message_end``.
    """
    if sink._closed:
        return
    with contextlib.suppress(Exception):
        sink.emit(message_end(FinishReason.CANCELLED))


def _emit_cancel_end_if_cancelling(sink: EventSink) -> None:
    """Emit terminal ``message_end`` when this task is unwinding from cancel."""
    task = asyncio.current_task()
    if task is None or not task.cancelling():
        return
    _emit_user_stop_message_end(sink)


class TurnExecutionMixin:
    def _log_turn_cancelled(
        self,
        *,
        turn_id: str,
        conversation_id: str,
        message_id: str | None,
        trace_id: str,
        content_chars: int,
        journal_entries: int,
        salvaged: bool,
    ) -> None:
        """Fingerprint CancelledError salvage (RPC stamp vs process/internal cancel)."""
        from agentcore.sidecar.server_pkg.cancel_mark import cancel_reason_from_task

        task = asyncio.current_task()
        logger.info(
            "sidecar.turn_cancelled",
            turn_id=turn_id,
            conversation_id=conversation_id or None,
            message_id=message_id,
            trace_id=trace_id or None,
            reason=cancel_reason_from_task(task),
            salvaged=salvaged,
            content_chars=content_chars,
            journal_entries=journal_entries,
        )

    async def _run_turn(self, request_id: Any, turn_id: str, params: dict[str, Any]) -> None:
        """Run one turn on the local engine; stream events; reply when done."""
        assert self._root is not None  # guarded by _on_start_turn
        conversation_id = str(params.get("conversationId") or turn_id)
        user_message = str(params.get("userMessage") or "")
        history = params.get("history") or []
        # The desktop mints one trace_id per local turn and threads it here + into the
        # write-back, so this turn's proxied LLM calls and its persisted reply share it.
        trace_id = str(params.get("traceId") or "")
        # Optimistic user bubble id — outbox idempotency anchor (as-built: 双模式工作区 §10.3).
        user_message_id = str(params.get("userMessageId") or "").strip() or new_id()
        # mint assistant message_id up front (cloud turn_runner posture) so begin_turn /
        # content checkpoints / journal share one id before the pipeline runs.
        message_id = new_id()

        turn_creds = self._creds_for(conversation_id, trace_id, message_id)

        sink = EventSink()
        backend = self._make_backend(external_mounts=params.get("externalMounts"))
        saver, deleter = self._suspension_hooks()
        outbox = self._outbox_store
        if outbox is not None:
            outbox.bind_turn(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                user_message=user_message,
                message_id=message_id,
                trace_id=trace_id,
            )
            await outbox.begin_turn(
                conversation_id=conversation_id,
                message_id=message_id,
                trace_id=trace_id,
            )
            sink.bind_content_checkpoint(
                conversation_id=conversation_id,
                message_id=message_id,
            )
        # A1+ local：message_id mint + begin_turn 之后、pipeline 之前打本机基线（resume 不重打）。
        from agentcore.workspace.turn_baseline import maybe_capture_turn_baseline

        await maybe_capture_turn_baseline(
            user_id=self._user_id,
            folder_id=None,
            conversation_id=conversation_id,
            message_id=message_id,
            backend=backend,
            workspace_root=self._root,
        )
        pump = asyncio.create_task(self._pump(turn_id, sink))
        try:
            try:
                # Bind the turn's trace_id here (the cloud binds it in stream_chat; the engine
                # itself doesn't) so the engine's message_start carries it and the live bubble
                # joins the same trace as the proxy logs + write-back (打通气泡↔日志, live ==
                # reload). Task-local + auto-restored; copied into delegated worker tasks.
                with log_context(
                    trace_id=trace_id,
                    conversation_id=conversation_id,
                    user_id=self._user_id,
                ):
                    from agentcore.sidecar import server as sidecar_server

                    # Sidecar is spawned only by the desktop Electron host. Pass
                    # platform=desktop so prepare builds DesktopClientChannel and
                    # MCP/Host discover over the existing ClientTool fulfill path
                    # (docs/06-规划/本机引擎MCP-Host回填接通定案.md P0). Never infer
                    # desktop_online from location=local.
                    result = await sidecar_server.run_chat_pipeline(
                        conversation_id=conversation_id,
                        user_message=user_message,
                        history=list(history),
                        sink=sink,
                        user_id=self._user_id,
                        backend=backend,
                        approvals_enabled=self._approvals_enabled,
                        permission_axes=self._permission_axes,
                        llm_credentials=turn_creds,
                        suspension_saver=saver,
                        suspension_deleter=deleter,
                        message_id=message_id,
                        x_client_platform="desktop",
                    )
                    # Pillar D1: keep sink open while a detached background drive is
                    # still live so run_completed / execution_completed reach the UI
                    # and outbox READY is not sealed mid-DURABLE append. Cancel /
                    # exception skip this await and still close below.
                    from agentcore.runtime.coordination import await_live_detached_drive

                    await await_live_detached_drive(conversation_id)
            finally:
                # Cancel path: emit confirmation *before* close so the pump still
                # delivers ``message_end(cancelled)`` (TURN_CANCELLED alone is not enough).
                _emit_cancel_end_if_cancelling(sink)
                # The pipeline no longer closes the sink (its owner does); the sidecar owns
                # this one, so close it on EVERY path — success or crash — or the pump would
                # await the None sentinel forever.
                sink.close()
            await pump  # sink closed above → all events flushed
            # finalize / READY only after close AND after any detached drive settled
            # (await above), so post-detach DURABLE journal appends are not dropped
            # by the outbox READY gate.
            if outbox is not None:
                await self._outbox_finalize(
                    outbox,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    user_message_id=user_message_id,
                    trace_id=trace_id,
                    result=result,
                )
            # Surface the model this turn actually ran on: creds present ⇒ the
            # cloud-proxy/account model; None (dev fallback) ⇒ settings.platform_model.
            await self._send(
                protocol.make_result(
                    request_id,
                    trim_result(turn_id, result, model=resolve_turn_model(turn_creds)),
                )
            )
        except asyncio.CancelledError:
            journal = list(sink.execution_journal() or [])
            content = sink.streamed_content() or ""
            if outbox is not None:
                await outbox.salvage(
                    journal=journal,
                    content=content,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    message_id=message_id,
                )
            self._log_turn_cancelled(
                turn_id=turn_id,
                conversation_id=conversation_id,
                message_id=message_id,
                trace_id=trace_id,
                content_chars=len(content),
                journal_entries=len(journal),
                salvaged=outbox is not None,
            )
            with contextlib.suppress(Exception):
                await pump
            # Reply on an independent task: this one is unwinding from cancellation.
            self._send_soon(
                protocol.make_error(request_id, protocol.TURN_CANCELLED, "turn cancelled")
            )
            raise
        except Exception as e:
            if outbox is not None:
                await outbox.salvage(
                    journal=list(sink.execution_journal() or []),
                    content=sink.streamed_content() or "",
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    message_id=message_id,
                )
            with contextlib.suppress(Exception):
                await pump
            logger.error("sidecar.turn_failed", turn_id=turn_id, error=str(e), exc_info=True)
            await self._send(protocol.make_error(request_id, protocol.INTERNAL_ERROR, str(e)))
        finally:
            if outbox is not None:
                outbox.clear_turn()
            self._unregister_turn(turn_id)

    async def _outbox_finalize(
        self,
        outbox: Any,
        *,
        conversation_id: str,
        user_message: str,
        user_message_id: str,
        trace_id: str,
        result: dict[str, Any],
    ) -> None:
        """Seal the outbox record as ready for main-process writeback."""
        journal_entries = result.get("journal_entries")
        runs = runs_from_entries(journal_entries) if journal_entries else None
        await outbox.finalize(
            mode="local",
            conversation_id=conversation_id,
            user_message=user_message,
            user_message_id=user_message_id,
            assistant_content=result.get("content") or "",
            assistant_reasoning=result.get("reasoning_content"),
            citations=result.get("citations") or [],
            runs=runs,
            # Complete result journal replaces progressive mid-run map when present.
            journal_entries=journal_entries if isinstance(journal_entries, list) else None,
            message_id=result.get("message_id"),
            input_tokens=int(result.get("input_tokens", 0) or 0),
            output_tokens=int(result.get("output_tokens", 0) or 0),
            reasoning_tokens=int(result.get("reasoning_tokens", 0) or 0),
            cache_hit_tokens=int(result.get("cache_hit_tokens", 0) or 0),
            cache_miss_tokens=int(result.get("cache_miss_tokens", 0) or 0),
            rounds=int(result.get("rounds", 0) or 0),
            trace_id=trace_id,
            finish_reason=_finish_str(result),
        )

    async def _run_resume(
        self,
        request_id: Any,
        suspension: TurnSuspension,
        decision: CheckpointDecision,
        note: str,
        selected: list[str],
        trace_id: str = "",
        user_message_id: str = "",
        external_mounts: list | dict | None = None,
    ) -> None:
        """Rebuild + finish a durably-paused turn; stream events; reply when done.

        D1: settlement is prewritten to the local outbox journal **before** the
        pipeline; on success the claimed frame is consumed immediately
        (:meth:`confirm_claim`). Pipeline failure after that does **not** restore
        the frame (decision card stays settled; user continues via a new message).
        """
        assert self._root is not None  # guarded by _on_resume
        turn_id = suspension.message_id
        conversation_id = suspension.conversation_id
        user_message = suspension.user_message or ""
        # Prefer the client-pinned user bubble id; fall back to a stable derived key.
        umid = (user_message_id or getattr(suspension, "user_message_id", None) or "").strip()
        if not umid:
            umid = f"resume-{turn_id}"
        decision_value = decision.value if hasattr(decision, "value") else str(decision)
        # Resolved once so the pipeline runs on it AND the reply surfaces the same model.
        resume_creds = self._creds_for(conversation_id, trace_id, turn_id)
        sink = EventSink()
        backend = self._make_backend(external_mounts=external_mounts)
        saver, deleter = self._suspension_hooks()
        outbox = self._outbox_store
        settlement_durable = False
        if outbox is not None:
            outbox.bind_turn(
                conversation_id=conversation_id,
                user_message_id=umid,
                user_message=user_message,
                message_id=turn_id,
                trace_id=trace_id,
            )
            await outbox.begin_turn(
                conversation_id=conversation_id,
                message_id=turn_id,
                trace_id=trace_id,
            )
            sink.bind_content_checkpoint(
                conversation_id=conversation_id,
                message_id=turn_id,
            )

        # D1: prewrite settlement → confirm_claim before any pipeline work.
        if outbox is not None:
            try:
                from agentcore.sidecar.settlement_prewrite import (
                    prewrite_sidecar_resume_settlement,
                )

                await prewrite_sidecar_resume_settlement(
                    outbox,
                    suspension,
                    decision=decision_value,
                    note=note,
                    selected=selected,
                    user_message_id=umid,
                    trace_id=trace_id,
                )
            except Exception as e:
                if self._paused_store is not None:
                    await self._paused_store.rollback_claim(turn_id)
                if outbox is not None:
                    outbox.clear_turn()
                self._unregister_turn(turn_id)
                logger.warning(
                    "sidecar.resume_settlement_prewrite_failed",
                    turn_id=turn_id,
                    error=str(e),
                )
                await self._send(
                    protocol.make_error(
                        request_id,
                        protocol.RESUME_RETRYABLE,
                        f"settlement prewrite failed: {e}",
                    )
                )
                return
            if self._paused_store is not None:
                await self._paused_store.confirm_claim(turn_id)
            settlement_durable = True
        else:
            # No outbox ⇒ cannot durable-prewrite; keep legacy confirm-on-success.
            settlement_durable = False

        pump = asyncio.create_task(self._pump(turn_id, sink))
        try:
            try:
                # Bind this continuation's trace_id (same rationale as _run_turn) so the
                # resumed reply's message_start + local logs join its proxy logs + write-back.
                with log_context(
                    trace_id=trace_id,
                    conversation_id=conversation_id,
                    user_id=self._user_id,
                ):
                    from agentcore.sidecar import server as sidecar_server

                    result = await sidecar_server.resume_chat_pipeline(
                        suspension=suspension,
                        decision=decision,
                        note=note,
                        selected=selected,
                        sink=sink,
                        backend=backend,
                        # The Sidecar has no message DB, so the prior-turn history rides in the
                        # local frame record (rehydrated onto the suspension at claim) — the resume
                        # splices it ahead of the journal-folded rounds (Phase 2 ⑤).
                        history=suspension.history,
                        llm_credentials=resume_creds,
                        suspension_saver=saver,
                        suspension_deleter=deleter,
                        permission_axes=self._permission_axes,
                        # Same desktop channel as fresh turns — omit ⇒ resume drops MCP/Host.
                        x_client_platform="desktop",
                    )
                    # Same D1 hold as _run_turn: delay close while detached drive lives.
                    from agentcore.runtime.coordination import await_live_detached_drive

                    await await_live_detached_drive(conversation_id)
            finally:
                _emit_cancel_end_if_cancelling(sink)
                # The pipeline no longer closes the sink (its owner does); the sidecar owns
                # this one, so close it on EVERY path — success or crash — or the pump would
                # await the None sentinel forever.
                sink.close()
            await pump  # sink closed above → all events flushed
            # finalize / READY only after close AND after any detached drive settled.
            if outbox is not None:
                await self._outbox_finalize(
                    outbox,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    user_message_id=umid,
                    trace_id=trace_id,
                    result=result,
                )
            # Same model signal as a start turn (see _run_turn): the resumed reply reports
            # the model it actually ran on so the badge stays honest across a resume.
            await self._send(
                protocol.make_result(
                    request_id,
                    trim_result(turn_id, result, model=resolve_turn_model(resume_creds)),
                )
            )
        except asyncio.CancelledError:
            # Settlement already durable ⇒ do not restore the decision card.
            if not settlement_durable and self._paused_store is not None:
                await self._paused_store.rollback_claim(turn_id)
            # G8: streamed_content is live-only; join hang-frame pre_pause.
            # Journal: merge hang-frame process_* with live (symmetric to content).
            from agentcore.conversation.turn_persistence import (
                compose_salvage_content,
                compose_salvage_journal,
            )

            journal = compose_salvage_journal(
                sink.execution_journal() or [],
                suspension.journal_entries,
            )
            content = compose_salvage_content(
                sink.streamed_content() or "",
                suspension.journal_entries,
            )
            if outbox is not None:
                await outbox.salvage(
                    journal=journal,
                    content=content,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    message_id=turn_id,
                )
            self._log_turn_cancelled(
                turn_id=turn_id,
                conversation_id=conversation_id,
                message_id=turn_id,
                trace_id=trace_id,
                content_chars=len(content or ""),
                journal_entries=len(journal or []),
                salvaged=outbox is not None,
            )
            with contextlib.suppress(Exception):
                await pump
            self._send_soon(
                protocol.make_error(request_id, protocol.TURN_CANCELLED, "turn cancelled")
            )
            raise
        except Exception as e:
            if not settlement_durable and self._paused_store is not None:
                await self._paused_store.rollback_claim(turn_id)
            if outbox is not None:
                from agentcore.conversation.turn_persistence import (
                    compose_salvage_content,
                    compose_salvage_journal,
                )

                await outbox.salvage(
                    journal=compose_salvage_journal(
                        sink.execution_journal() or [],
                        suspension.journal_entries,
                    ),
                    content=compose_salvage_content(
                        sink.streamed_content() or "",
                        suspension.journal_entries,
                    ),
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    message_id=turn_id,
                )
            with contextlib.suppress(Exception):
                await pump
            logger.error("sidecar.resume_failed", turn_id=turn_id, error=str(e), exc_info=True)
            # After settlement, failure does not restore the frame for retry.
            err_code = protocol.INTERNAL_ERROR if settlement_durable else protocol.RESUME_RETRYABLE
            await self._send(
                protocol.make_error(
                    request_id,
                    err_code,
                    str(e),
                )
            )
        else:
            if not settlement_durable and self._paused_store is not None:
                await self._paused_store.confirm_claim(turn_id)
        finally:
            if outbox is not None:
                outbox.clear_turn()
            self._unregister_turn(turn_id)

    async def _pump(self, turn_id: str, sink: EventSink) -> None:
        """Drain the turn's EventSink, emitting each event as a notification.

        Mirrors the SSE layer's ``_event_generator`` consumer: pull until the sink
        is closed (``None``), forwarding every event verbatim. ``StrEnum`` values in
        the payload (``EventType`` / ``FinishReason``) serialize as plain strings.
        """
        while True:
            event = await sink.get()
            if event is None:
                return
            await self._send(
                protocol.make_notification(
                    "turn/event",
                    {
                        "turnId": turn_id,
                        "event": {
                            "type": event.type.value,
                            "timestamp": event.timestamp,
                            "payload": event.payload,
                        },
                    },
                )
            )
