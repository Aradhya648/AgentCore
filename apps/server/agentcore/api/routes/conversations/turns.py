"""Turn re-execution and durable resume: regenerate / list paused / resume (结构化挂起)."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_db,
)
from agentcore.api.schemas import (
    PausedTurnSummary,
    PendingInteractionSummary,
    RegenerateMessageRequest,
    ResumeTurnRequest,
    RetryFailedRequest,
    TurnRecoveryResponse,
)
from agentcore.api.sse import sse_response
from agentcore.conversation.rate_limit import enforce_user_message_rate_limit
from agentcore.conversation.service import regenerate_chat, resume_chat, retry_failed_chat
from agentcore.core.errors import NotFoundError
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import ConversationRepository, TurnJournalRepository
from agentcore.runtime.checkpoints import CheckpointResponse
from agentcore.runtime.events import EventSink
from agentcore.runtime.interaction_orphan import orphan_registry_pending
from agentcore.runtime.journal.pending_interactions import fold_pending_interactions
from agentcore.runtime.settlement import prewrite_cold_resume_settlement
from agentcore.runtime.suspension import TurnSuspension, suspension_summary_fields
from agentcore.runtime.suspension_persistence import (
    claim_paused_turn,
    list_paused_turns,
    load_paused_turn,
)
from agentcore.runtime.turn_runs import turn_runs

from ._helpers import (
    _preflight_owned_chat_turn,
    _require_owned_conversation,
    emit_preflight_warnings,
    release_request_db_before_sse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _paused_summary(f: TurnSuspension) -> PausedTurnSummary:
    """Project one persisted suspension frame to its wire summary (shared by the
    paused-list + recovery endpoints). Kind-specific slots come from the shared
    :func:`~agentcore.runtime.suspension.suspension_summary_fields` codec registry
    (same source as the sidecar ``paused_summary``)."""
    return PausedTurnSummary(
        message_id=f.message_id,
        kind=f.kind,
        checkpoint_id=f.checkpoint_id,
        user_message=f.user_message,
        **suspension_summary_fields(f),
    )


async def _pending_interaction_summaries(
    conversation_id: str,
) -> list[PendingInteractionSummary]:
    """Journal-fold pending hot-path interactions for recovery (D5)."""
    run = turn_runs.get(conversation_id)
    turn_ids: list[str] = []
    if run is not None:
        mid = getattr(run.sink, "_message_id", None) or getattr(run.sink, "message_id", None)
        if mid:
            turn_ids.append(str(mid))

    async with async_session_factory() as db:
        if not turn_ids:
            # 会话时间序（max created_at），非 in-turn seq — 长回合不得挤掉旧卡。
            turn_ids = await TurnJournalRepository(db).list_recent_turn_ids(
                conversation_id, limit=40
            )

        out: list[PendingInteractionSummary] = []
        seen: set[str] = set()
        for turn_id in turn_ids:
            entries = await TurnJournalRepository(db).load(turn_id)
            for pending in fold_pending_interactions(entries, message_id=turn_id):
                if pending.id in seen:
                    continue
                seen.add(pending.id)
                out.append(
                    PendingInteractionSummary(
                        kind=pending.kind,  # type: ignore[arg-type]
                        id=pending.id,
                        message_id=pending.message_id,
                        payload=pending.payload,
                    )
                )
        return out


@router.post("/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate_message(
    conversation_id: str,
    message_id: str,
    body: RegenerateMessageRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
):
    """Re-run a turn from an existing user message via SSE.

    Serves both "regenerate" (no body content — reuse the stored user text) and
    "edit & resend" (``content`` set — edit the user message first). The target
    ``message_id`` must be a user message; the superseded assistant reply and any
    later turns are dropped before re-running. Like ``send_message``, the pipeline
    runs as a detached task tracked in the ``TurnRunRegistry`` and the SSE only
    attaches (执行与请求解耦 C1 · slice 1a): a disconnect lets it finish + persist,
    an explicit 停止 goes through ``POST .../stop``. A re-run is a fresh turn, so it
    passes the same gates (rate limit → ownership → BYOK/quota billing gate) as
    ``send_message``.
    """
    await enforce_user_message_rate_limit(user.user_id)

    preflight = await _preflight_owned_chat_turn(conversation_id, user, session)
    await release_request_db_before_sse(session)

    # 触发点④：regenerate 前 orphan 热路 pending
    await orphan_registry_pending(conversation_id)
    await turn_runs.stop_and_drain(conversation_id)

    sink = EventSink()
    emit_preflight_warnings(sink, preflight)

    task = asyncio.create_task(
        regenerate_chat(
            conversation_id=conversation_id,
            message_id=message_id,
            user_id=user.user_id,
            sink=sink,
            edited_content=body.content,
            llm_credentials=preflight.credentials,
            llm_supports_tools=preflight.supports_tools,
        )
    )
    turn_runs.register(conversation_id=conversation_id, task=task, sink=sink)

    return sse_response(sink, detach_on_disconnect=True)


@router.post("/{conversation_id}/messages/{message_id}/retry-failed")
async def retry_failed_message(
    conversation_id: str,
    message_id: str,
    _body: RetryFailedRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
):
    """Retry only the failed worker nodes from a previous turn's execution.

    Unlike regenerate (which re-runs everything), this extracts the completed
    worker states from the previous turn's journal and seeds them into a new
    pipeline run, so only failed nodes are re-executed.
    """
    await enforce_user_message_rate_limit(user.user_id)

    preflight = await _preflight_owned_chat_turn(
        conversation_id, user, session, needs_tools=True
    )
    await release_request_db_before_sse(session)

    # 触发点④：retry 前 orphan 热路 pending
    await orphan_registry_pending(conversation_id)
    await turn_runs.stop_and_drain(conversation_id)

    sink = EventSink()
    emit_preflight_warnings(sink, preflight)

    task = asyncio.create_task(
        retry_failed_chat(
            conversation_id=conversation_id,
            message_id=message_id,
            user_id=user.user_id,
            sink=sink,
            llm_credentials=preflight.credentials,
            llm_supports_tools=preflight.supports_tools,
        )
    )
    turn_runs.register(conversation_id=conversation_id, task=task, sink=sink)

    return sse_response(sink, detach_on_disconnect=True)


@router.get("/{conversation_id}/recovery", response_model=TurnRecoveryResponse)
async def get_conversation_recovery(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """One-shot recovery snapshot for a conversation reopen (recovery 统一, 对称 §8.2).

    Folds reopen probes into a single owner-gated read: live_running / paused /
    pending_interactions (journal fold of hot-path cards).
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    run = turn_runs.get(conversation_id)
    live_running = run is not None and not run.task.done()
    frames = await list_paused_turns(conversation_id)
    pending = await _pending_interaction_summaries(conversation_id)
    return TurnRecoveryResponse(
        live_running=live_running,
        paused=[_paused_summary(f) for f in frames],
        pending_interactions=pending,
    )


@router.post("/{conversation_id}/messages/{message_id}/resume")
async def resume_message(
    conversation_id: str,
    message_id: str,
    body: ResumeTurnRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
    x_client_platform: Annotated[str | None, Header(alias="X-Client-Platform")] = None,
):
    """Continue a durably-paused turn via SSE (结构化挂起 2b ``POST .../resume``).

    The turn paused at a plan_review / ask_user / team_preview checkpoint and lost its
    live stream (disconnect / restart); only its persisted frame survived.

    Settlement 预写 (D8)：① peek frame → ② live-task drain（不 cancel；仍 live ⇒ 409）→
    ③ ``*_resolved`` 落库成功 → ④ ``claim_paused_turn`` → ⑤ resume pipeline。settlement
    写失败 ⇒ 5xx、不 claim、frame 保留可重试。Claim 竞争失败按现状 404。settlement 落库后
    pipeline 取消/失败 ⇒ interrupted_after_decision（D1：不复活决策卡）。

    ``body.selected`` carries the user's ask_user picks (ignored for plan_review).
    ``body.style_id`` is the structured website style pick when present.
    Gated like ``send_message`` (it spends tokens): rate limit → ownership → BYOK/quota
    — all BEFORE settlement/claim, so a refused turn keeps its resumable frame.
    """
    await enforce_user_message_rate_limit(user.user_id)

    preflight = await _preflight_owned_chat_turn(conversation_id, user, session)
    await release_request_db_before_sse(session)

    peeked = await load_paused_turn(message_id, conversation_id=conversation_id)
    if peeked is None:
        raise NotFoundError("挂起的回合不存在或已处理")

    # D9: paused 不占锁，会话可另开新回合。Resume 不得 cancel 在跑回合——只等已收口残余
    # 解栈；仍 live ⇒ 409 且不 claim（帧保留可重试）。
    if not await turn_runs.drain(conversation_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "turn_in_progress",
                "message": "会话有正在进行的回合，先等它结束或显式停止",
            },
        )

    decision = body.decision.value if hasattr(body.decision, "value") else str(body.decision)
    try:
        await prewrite_cold_resume_settlement(
            peeked,
            decision=decision,
            note=body.note or "",
            selected=list(body.selected or []),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "resume.settlement_prewrite_failed",
            message_id=message_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "settlement_write_failed"},
        ) from e

    suspension = await claim_paused_turn(message_id, conversation_id=conversation_id)
    if suspension is None:
        raise NotFoundError("挂起的回合不存在或已处理")

    sink = EventSink()
    emit_preflight_warnings(sink, preflight)
    task = asyncio.create_task(
        resume_chat(
            suspension=suspension,
            response=CheckpointResponse(
                decision=body.decision,
                note=body.note,
                selected=body.selected,
                style_id=(body.style_id or "").strip(),
            ),
            sink=sink,
            llm_credentials=preflight.credentials,
            llm_supports_tools=preflight.supports_tools,
            x_client_platform=x_client_platform,
        )
    )
    # 执行与请求解耦 (C1 · slice 1a): track the resumed run so a disconnect lets it
    # finish + persist and 停止 routes through POST .../stop, same as a fresh send.
    turn_runs.register(conversation_id=conversation_id, task=task, sink=sink)
    return sse_response(sink, detach_on_disconnect=True)
