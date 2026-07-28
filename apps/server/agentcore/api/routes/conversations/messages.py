"""Conversation message routes: list / delete / send / stop / attach / local-turn.

Every route requires an authenticated user and is scoped to that user's own
conversations (IDOR-safe). Sending runs the turn as a detached task tracked in the
``TurnRunRegistry`` so a client disconnect no longer kills it (执行与请求解耦 C1).
"""

import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_db,
    get_memory_update_repo,
    get_message_repo,
    get_turn_journal_repo,
)
from agentcore.api.schemas import (
    MemoryUpdateView,
    MessageDetail,
    MessageListResponse,
    RecordTurnRequest,
    RecordTurnResponse,
    RunsPayload,
    SendMessageRequest,
    SetMessageFeedbackRequest,
    StatusResponse,
    StopTurnResponse,
)
from agentcore.api.schemas.messages import TurnCollabMetrics
from agentcore.api.sse import sse_attach_response, sse_queued_response, sse_response
from agentcore.conversation.rate_limit import enforce_user_message_rate_limit
from agentcore.conversation.service import record_local_turn, stream_chat
from agentcore.conversation.store import get_conversation_store
from agentcore.conversation.store.overlay import (
    overlay_message_fields,
    overlay_runs_with_segments,
)
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import (
    ConversationRepository,
    MemoryUpdateRepository,
    MessageRepository,
    TurnJournalRepository,
)
from agentcore.llm.resolve import resolve_user_llm_credentials
from agentcore.runtime.events import EventSink
from agentcore.runtime.journal import runs_from_entries_cached
from agentcore.runtime.journal.entries import _PROCESS_PREFIX
from agentcore.runtime.turn_runs import turn_runs

from ._helpers import (
    _preflight_owned_chat_turn,
    _require_owned_conversation,
    emit_preflight_warnings,
    release_request_db_before_sse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _persist_delivered_interjection_attachments(
    *,
    conversation_id: str,
    user_id: str,
    attachments: list[dict],
    sink: EventSink,
) -> list[dict]:
    """Persist mid-flight interjection attachments into the conversation workspace.

    Same ``persist_attachments`` path as a normal turn. Returns enriched dicts
    (``workspace_path`` set, inline ``text`` retained) for stash / later drain.
    """
    if not attachments:
        return []

    from agentcore.conversation.common import resolve_local_binding
    from agentcore.conversation.turn_backend import build_turn_backend
    from agentcore.db import async_session_factory
    from agentcore.workspace.attachments import persist_attachments
    from agentcore.workspace.locate import workspace_storage_key
    from agentcore.workspace.locks import workspace_lock

    async with async_session_factory() as session:
        conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
        if not conv:
            return attachments
        folder_id = conv.folder_id
        local_binding = await resolve_local_binding(session, conv)

    backend = await build_turn_backend(
        user_id=user_id,
        conversation_id=conversation_id,
        folder_id=folder_id,
        sink=sink,
        local_binding=local_binding,
    )
    async with workspace_lock(
        workspace_storage_key(
            user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
        )
    ):
        return await persist_attachments(backend, attachments)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: str,
    user: AuthUser,
    limit: int = Query(100, ge=1, le=200),
    before: datetime | None = Query(None),
    after: datetime | None = Query(None),
    around: str | None = Query(None),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    repo: MessageRepository = Depends(get_message_repo),
    journal_repo: TurnJournalRepository = Depends(get_turn_journal_repo),
    mem_update_repo: MemoryUpdateRepository = Depends(get_memory_update_repo),
):
    """A window of a conversation's messages (cursor-windowed, chronological).

    Four mutually-exclusive modes (checked in this order):

    - ``around={message_id}``: a window centered on a message — the search-hit jump
      (load-around B). 404 if the message isn't in this conversation.
    - ``before={iso}``: the page strictly older than the cursor (scroll up).
    - ``after={iso}``: the page strictly newer than the cursor (scroll down).
    - none: the latest window (conversation open).

    ``has_more_before`` / ``has_more_after`` drive infinite scroll; a one-sided
    query computes only the flag for the direction it moves in (an ``around`` window
    computes both). ``total`` is the conversation's full message count.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    total = await repo.count_by_conversation(conversation_id)

    has_more_before = False
    has_more_after = False
    if around is not None:
        window = await repo.window_around(
            conversation_id, message_id=around, before=limit, after=limit
        )
        if window is None:
            raise NotFoundError("消息不存在")
        messages, has_more_before, has_more_after = window
    elif before is not None:
        messages, has_more_before = await repo.list_before(
            conversation_id, before=before, limit=limit
        )
    elif after is not None:
        messages, has_more_after = await repo.list_after(conversation_id, after=after, limit=limit)
    else:
        messages, has_more_before = await repo.list_latest(conversation_id, limit=limit)

    # Project each assistant message's replay payload (runs) from the唯一事实源
    # turn_journal (§8.3) — it is no longer stored on the message row. One batched
    # query over the page's message ids (no N+1); turns with no facts stay runs=None.
    # The per-row fold is memoized by (message_id, journal version) so re-opening /
    # reloading a window doesn't re-project unchanged turns (项目审计-成本性能专项 PERF-003).
    journal_map = await journal_repo.load_map([m.id for m in messages])
    # Batch-load in-flight stream segments for overlay (P1 · §3.3).
    stream_map = await get_conversation_store().list_stream_segments_map(
        turn_ids=[m.id for m in messages]
    )
    details: list[MessageDetail] = []
    for m in messages:
        detail = MessageDetail.model_validate(m)
        usage = m.usage or {}
        segments = stream_map.get(m.id) or []
        runs = runs_from_entries_cached(m.id, journal_map.get(m.id))
        runs = overlay_runs_with_segments(runs, segments, usage=usage)
        if runs is not None:
            detail.runs = RunsPayload.model_validate(runs)
        # 回合轮次 (Tier 2 重载): rounds shares the row's usage column but has no own
        # attribute, so project it on read (usage itself is normalized by the schema
        # validator). Drives the bubble's「N 轮」caption alongside usage.
        rounds = usage.get("rounds")
        if rounds is not None:
            detail.rounds = rounds
        # Assistant-row lifecycle (usage.status) — overlay criterion for stream_state.
        status = usage.get("status")
        if status is not None:
            detail.status = status
        # Cold-path pause latch (usage.paused): write keeps status=running; lift so clients
        # hydrate as paused rather than streaming.
        if usage.get("paused"):
            detail.paused = True
        # System provenance (usage.origin) — e.g. execution_harvest synthetic user rows.
        origin = usage.get("origin")
        if isinstance(origin, str) and origin.strip():
            detail.origin = origin.strip()
        # In-flight overlay: fill content / reasoning from turn_stream_state when running.
        # When journal already has process_content, skip captain:content → messages.content
        # (deliverable_only: narration lives on the process lane, not the content column).
        if segments:
            journal_rows = journal_map.get(m.id) or []
            from agentcore.runtime.events.attach_replay import journal_is_structured

            skip_cap_content = any(
                (e.get("kind") or "") == f"{_PROCESS_PREFIX}content" for e in journal_rows
            ) or journal_is_structured(journal_rows)
            content, reasoning = overlay_message_fields(
                content=detail.content,
                reasoning_content=detail.reasoning_content,
                segments=segments,
                usage=usage,
                skip_captain_content=skip_cap_content,
            )
            detail.content = content or ""
            detail.reasoning_content = reasoning
        collab = usage.get("collab")
        if collab is not None:
            detail.collab = TurnCollabMetrics.model_validate(collab)
        details.append(detail)

    # 记忆更新对话内可见 (§1.6): the conversation-tail「记忆已更新」cards. They sit AFTER
    # the last message, so they belong only to the LATEST window (no before/after/around) —
    # scroll-up / search-hit pages skip the read entirely.
    memory_updates: list[MemoryUpdateView] = []
    if around is None and before is None and after is None:
        memory_updates = [
            MemoryUpdateView.model_validate(row)
            for row in await mem_update_repo.list_for_conversation(conversation_id)
        ]

    return MessageListResponse(
        data=details,
        total=total,
        has_more_before=has_more_before,
        has_more_after=has_more_after,
        memory_updates=memory_updates,
    )


@router.delete("/{conversation_id}/messages/{message_id}", response_model=StatusResponse)
async def delete_message(
    conversation_id: str,
    message_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    repo: MessageRepository = Depends(get_message_repo),
):
    """Delete a single message (单条消息删除).

    Owner-scoped: proving ownership of the conversation first, then deleting only
    within it, means a guessed ``message_id`` from another user's chat can't be
    removed (404 on a foreign/absent conversation; no-op-then-404 on an absent
    message). Append-only ``cost_events`` are intentionally preserved — deleting a
    message never rewrites real spend (不变量 #1).
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    deleted = await repo.delete_by_id(message_id, conversation_id=conversation_id)
    if not deleted:
        raise NotFoundError("消息不存在")
    return StatusResponse()


@router.patch("/{conversation_id}/messages/{message_id}/feedback", response_model=StatusResponse)
async def set_message_feedback(
    conversation_id: str,
    message_id: str,
    body: SetMessageFeedbackRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    repo: MessageRepository = Depends(get_message_repo),
):
    """Set / clear the user's 点赞/点踩 on an assistant reply (回复反馈).

    Owner-scoped like delete (prove conversation ownership first, then update only within
    it, so a guessed cross-user ``message_id`` can't be rated — IDOR-safe). ``feedback`` is
    ``"up"`` / ``"down"`` to rate, or ``null`` to clear the rating (toggling the same side
    off). 404 when the message isn't in this conversation.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    updated = await repo.set_feedback(
        message_id, conversation_id=conversation_id, feedback=body.feedback
    )
    if not updated:
        raise NotFoundError("消息不存在")
    return StatusResponse()


@router.post(
    "/{conversation_id}/messages",
    # response_class 压掉 FastAPI 默认 200 application/json 空 schema——本端点恒返回
    # SSE（发送即有流），200 契约只声明 text/event-stream。
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "SSE stream (发送即有流): idle turn / FIFO queue wait+续流 / "
                "coordination interjection ack"
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        409: {"description": "Hot-path pending interaction blocks new messages"},
    },
)
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
    x_client_platform: Annotated[str | None, Header(alias="X-Client-Platform")] = None,
):
    """Send a user message and get a streaming AI response via SSE.

    执行与请求解耦 (C1 · slice 1a): the pipeline runs as a *detached* task tracked in
    the ``TurnRunRegistry`` (keyed by conversation), and the SSE stream only attaches
    to it (``detach_on_disconnect=True``). A client disconnect therefore no longer
    kills the turn (案例 1: 7-min 断连即丢交付) — it finishes + persists in the
    background; an explicit 停止 routes through ``POST .../stop`` instead.

    发送即有流 (D9): this endpoint **always** returns SSE (never 202 JSON).

    - **空闲** → 现行为：开跑并流式推送整个回合。
    - **经典 in-flight（无协调）** → FIFO 入队，立即 ``turn_queued``，drain 启动后
      **同一连接**续流该回合；等待中断连 → 回合仍 detached 跑，靠 attach/recovery。
    - **协调模式** → 插话进 CEO 事件队列，SSE 上复用 ``user_interjection``（短流确认）。
    - **热路 pending**（approval / escalation / …）仍 409。

    Gated before the stream starts (成本配额与计费.md §一) so a refused turn gets a
    clean error instead of a half-opened SSE: per-user rate limit first (sheds a
    flooding account before any resource DB work), then ownership, then the
    BYOK/quota billing gate (BYOK mode requires the user's own key; platform mode
    enforces quota). The resolved BYOK credentials thread through the whole turn.

    Request-scoped DB session for preflight only — explicitly closed before the SSE
    stream opens so a long-lived stream never holds a pooled connection (fixes
    GC-termination warnings on abrupt teardown).
    """
    await enforce_user_message_rate_limit(user.user_id)

    # 提问确认交互统一 D9：热路挂起中同对话发新消息 → 409（regenerate/retry 不拦）
    from agentcore.runtime.interaction import InteractionKind, default_interaction_registry

    _hot = frozenset(
        {
            InteractionKind.APPROVAL,
            InteractionKind.DELEGATION_AUTHORIZATION,
            InteractionKind.ESCALATION,
        }
    )
    hot_pending = [
        r
        for r in default_interaction_registry().list_pending(conversation_id)
        if r.kind in _hot
        and not (
            r.kind is InteractionKind.ESCALATION and (r.payload or {}).get("awaiting") == "ceo"
        )
    ]
    if hot_pending:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail={
                "code": "pending_interactions_awaiting",
                "pending_kinds": sorted({r.kind.value for r in hot_pending}),
            },
        )

    # 批 B 失效修订：发消息不再立即 orphan；回合收尾若未调 debate / 未起 MLR 才落事实。

    needs_tools = body.requires_tools
    preflight = await _preflight_owned_chat_turn(
        conversation_id, user, session, needs_tools=needs_tools
    )
    await release_request_db_before_sse(session)

    # In-flight turn → coordination inject or conversation-level queue (both SSE).
    existing = turn_runs.get(conversation_id)
    if existing is not None and not existing.task.done():
        from agentcore.core.types import new_id
        from agentcore.runtime.coordination.session import (
            CoordinationEvent,
            CoordinationEventKind,
            active_coordination_for_conversation,
        )
        from agentcore.runtime.events import user_interjection
        from agentcore.runtime.turn_queue import new_queued_turn, turn_queue

        coord = active_coordination_for_conversation(conversation_id)
        if coord is not None and coord.active:
            interjection_id = new_id()
            raw_attachments = [a.model_dump() for a in body.attachments]
            # Delivered path: persist now so CEO / queue_user_message see workspace_path.
            # Stash keeps inline text; a later drain re-pass is idempotent (path set → skip write).
            from agentcore.workspace.attachments import interjection_attachment_meta

            attachments = await _persist_delivered_interjection_attachments(
                conversation_id=conversation_id,
                user_id=user.user_id,
                attachments=raw_attachments,
                sink=existing.sink,
            )
            att_meta = interjection_attachment_meta(attachments)
            coord.stash_interjection(
                interjection_id,
                {
                    "content": body.content,
                    "user_id": user.user_id,
                    "conversation_id": conversation_id,
                    "attachments": attachments,
                    "requires_tools": needs_tools,
                    "x_client_platform": x_client_platform,
                    "llm_credentials": preflight.credentials,
                    "llm_supports_tools": preflight.supports_tools,
                },
            )
            posted = coord.post(
                CoordinationEvent(
                    kind=CoordinationEventKind.USER_INTERJECTION,
                    payload={
                        "interjection_id": interjection_id,
                        "content": body.content,
                        **({"attachments": att_meta} if att_meta else {}),
                    },
                )
            )
            if not posted:
                # Session closing between lookup and post — fall through to queue.
                coord.take_interjection(interjection_id)
            else:
                # Live turn observers see the interjection on the in-flight sink.
                existing.sink.emit(
                    user_interjection(
                        interjection_id=interjection_id,
                        execution_id=coord.execution_id,
                        content=body.content,
                        status="delivered",
                        attachments=att_meta or None,
                    )
                )
                # Sender's POST always gets SSE (发送即有流): short confirm stream.
                confirm = EventSink()
                confirm.emit(
                    user_interjection(
                        interjection_id=interjection_id,
                        execution_id=coord.execution_id,
                        content=body.content,
                        status="delivered",
                        attachments=att_meta or None,
                    )
                )
                confirm.close()
                return sse_response(confirm, detach_on_disconnect=True)

        started: asyncio.Future = asyncio.get_running_loop().create_future()
        # enqueue_and_ensure_drain（非裸 enqueue）：协调 fall-through 前的附件落盘 await
        # 期间宿主回合可能已结束——彼时队列还空，done-callback 的 schedule_drain 已 no-op；
        # 入队后重查槽位补 arm，否则该项永久搁浅、本连接卡死在 await started。
        status = turn_queue.enqueue_and_ensure_drain(
            conversation_id,
            new_queued_turn(
                content=body.content,
                user_id=user.user_id,
                attachments=[a.model_dump() for a in body.attachments],
                requires_tools=needs_tools,
                x_client_platform=x_client_platform,
                llm_credentials=preflight.credentials,
                llm_supports_tools=preflight.supports_tools,
                started=started,
            ),
        )
        return sse_queued_response(
            conversation_id=conversation_id,
            queue_id=status.queue_id,
            position=status.position,
            queue_depth=status.queue_depth,
            started=started,
        )

    sink = EventSink()
    emit_preflight_warnings(sink, preflight)

    task = asyncio.create_task(
        stream_chat(
            conversation_id=conversation_id,
            user_message=body.content,
            user_id=user.user_id,
            sink=sink,
            attachments=[a.model_dump() for a in body.attachments],
            llm_credentials=preflight.credentials,
            llm_supports_tools=preflight.supports_tools,
            x_client_platform=x_client_platform,
        )
    )
    turn_runs.register(conversation_id=conversation_id, task=task, sink=sink)

    return sse_response(sink, detach_on_disconnect=True)


@router.post("/{conversation_id}/stop", response_model=StopTurnResponse)
async def stop_message(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Explicitly stop the conversation's in-flight turn (执行与请求解耦 C1 · slice 1a).

    Now that a client disconnect no longer cancels a turn (it runs to completion +
    persists in the background), the user's 「停止」 routes here instead. Cancels the
    detached run task tracked in the ``TurnRunRegistry``, which unwinds through the
    turn's ``CancelledError`` salvage — finished team work is kept as an incomplete
    message. Also cascade-cancels any live coordination drive + in-flight workers
    (unlike SSE disconnect, which detaches and lets the team finish). Idempotent:
    ``stopped=false`` when nothing is running (already finished / never started), so
    a late click settles cleanly. Owner-gated.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    # 触发点④：stop 前 orphan 热路 pending
    from agentcore.runtime.interaction_orphan import orphan_registry_pending

    await orphan_registry_pending(conversation_id)
    stopped = turn_runs.stop(conversation_id)
    if not stopped:
        # Detached background execution with no live turn slot — cancel via registry.
        from agentcore.runtime.coordination.session import (
            cancel_coordination_on_user_stop,
        )

        stopped = cancel_coordination_on_user_stop(conversation_id)
    return StopTurnResponse(stopped=stopped)


@router.get("/{conversation_id}/stream")
async def attach_stream(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    """Re-attach to the conversation's in-flight turn and 续看 it live (C1 · slice 1b).

    Since a disconnect no longer cancels a turn (slice 1a — it runs detached + persists
    in the background), a client that dropped (network blip) or reopened the app can
    rejoin the live run here: the SSE replays the transcript so far (coalesced — one
    content / reasoning block, the team graph, finished tool calls) then tails new
    events, all in the SAME event shape as the original stream, so the client folds it
    through one dispatch path.

    With ``Last-Event-ID`` (P3): journal-backed full-turn durable replay + stream_state
    synthetic deltas (header value observational — clients clear-then-fold), then live
    tail. Without the header (same-process fast path): ``EventSink.take_over`` full
    ``_history`` replay.

    Returns ``204 No Content`` when no run is live for the conversation (already
    finished / never started / suspended at a checkpoint) — the client then falls back
    to the persisted transcript (reload) / durable resume. A pure observer: dropping
    this stream detaches again (never cancels); an explicit 停止 still goes through
    ``POST .../stop``. Owner-gated.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    run = turn_runs.get(conversation_id)
    if run is None or run.task.done():
        return Response(status_code=204)
    cursor: int | None = None
    if last_event_id is not None:
        raw = last_event_id.strip()
        if raw.isdigit():
            cursor = int(raw)
    return sse_attach_response(run.sink, last_event_id=cursor)


@router.post("/{conversation_id}/local-turns", response_model=RecordTurnResponse)
async def record_local_turn_endpoint(
    conversation_id: str,
    body: RecordTurnRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Persist a turn that ran on the user's machine via the sidecar (双模式工作区 §一.1).

    The local engine produced the reply on the user's box (no server SSE turn ran),
    so the desktop reports the finished turn here to land it in durable history.
    Owner-scoped (404 for a non-owner). Spend is NOT recorded here — a sidecar turn's
    LLM calls are metered authoritatively at the cloud inference proxy (``/v1/inference``,
    Slice 4a); this endpoint persists content only.

    Unlike ``send_message`` there is NO pre-turn billing gate — the turn already
    happened on the user's machine; this only RECORDS its content. The write-back is
    idempotent so the desktop can safely retry a flaky POST: messages dedupe on the
    client-minted ``user_message_id``, so a retry after a committed-but-lost response
    never duplicates the turn. The title is generated best-effort on the user's resolved
    BYOK key (None → platform fallback).
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    # Best-effort credentials for the title pass — unlike send_message's preflight we
    # never REFUSE here (the turn is already done; recording must not be blockable).
    credentials = await resolve_user_llm_credentials(session, user.user_id)
    result = await record_local_turn(
        conversation_id=conversation_id,
        user_id=user.user_id,
        user_message=body.user_message,
        assistant_content=body.content,
        assistant_reasoning=body.reasoning_content,
        citations=[c.model_dump() for c in body.citations] or None,
        evidence_ledger=[e.model_dump() for e in body.evidence_ledger] or None,
        runs=body.runs.model_dump() if body.runs else None,
        journal=body.journal,
        user_message_id=body.user_message_id,
        message_id=body.message_id,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        reasoning_tokens=body.reasoning_tokens,
        cache_hit_tokens=body.cache_hit_tokens,
        cache_miss_tokens=body.cache_miss_tokens,
        rounds=body.rounds,
        trace_id=body.trace_id,
        finish_reason=body.finish_reason,
        llm_credentials=credentials,
    )
    return RecordTurnResponse(**result)
