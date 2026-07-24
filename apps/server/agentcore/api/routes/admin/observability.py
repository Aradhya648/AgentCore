"""Operational observability + conversation replay (运营观测看板 / 会话复盘)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.admin.audit import record_admin_audit
from agentcore.api.dependencies import (
    AdminUser,
    get_conversation_repo,
    get_cost_event_repo,
    get_db,
    get_message_repo,
    get_turn_journal_repo,
    get_turn_metrics_repo,
    get_user_repo,
)
from agentcore.api.routes.admin._shared import (
    _TREND_DAYS,
    _health_window,
    _project_spans,
)
from agentcore.api.schemas import (
    AdminConversationReplay,
    AdminObservabilitySummary,
    DailyTurns,
    ReplayConversation,
    ReplayMessage,
    TurnMetricLine,
)
from agentcore.config import settings
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import (
    ConversationRepository,
    CostEventRepository,
    MessageRepository,
    TurnJournalRepository,
    TurnMetricsRepository,
    UserRepository,
)

router = APIRouter(tags=["admin"])

# 观测看板「近期错误」feed length — the recent failures worth a glance (the long tail
# is for the drill-down, not the dashboard).
_ERROR_FEED = 20
# 会话复盘 message cap: one conversation's thread is bounded for the timeline payload
# (a conversation rarely exceeds this; deeper history is a paginated concern later).
_REPLAY_MAX_MESSAGES = 500


@router.get("/observability/summary", response_model=AdminObservabilitySummary)
async def observability_summary(
    admin: AdminUser,
    repo: TurnMetricsRepository = Depends(get_turn_metrics_repo),
) -> AdminObservabilitySummary:
    """运营观测看板 (观测, P1): platform-wide turn health (today + trailing 7 days),
    the 7-day daily trend, and the most recent errored turns.

    Sourced from ``turn_metrics`` (the per-turn telemetry sink), NOT the dev log
    file — so it works under prod's stdout-only logging posture and aggregates with
    indexed SQL instead of scanning a multi-MB JSONL. Aggregated over *every*
    account (admin is a cross-user surface). Each error row carries its ``trace_id``
    / ``conversation_id`` to drill from a failure into the full turn (会话复盘, P2).
    """
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # The trailing-7-day window shares its start with the trend so「近 7 日」health and
    # the trend bars span exactly the same UTC days.
    week_start = day_start - timedelta(days=_TREND_DAYS - 1)

    today = await repo.aggregate_health_for_window(since=day_start)
    week = await repo.aggregate_health_for_window(since=week_start)

    # 近 7 日趋势: zero-fill the daily map into a fixed, oldest-first series ending
    # today so the bars are a stable length even on a quiet day.
    daily = await repo.aggregate_daily_for_window(since=week_start)
    recent_daily = []
    for i in range(_TREND_DAYS):
        iso = (week_start + timedelta(days=i)).date().isoformat()
        point = daily.get(iso) or {}
        recent_daily.append(
            DailyTurns(
                date=iso,
                turns=int(point.get("turns", 0)),
                errors=int(point.get("errors", 0)),
            )
        )

    errors = await repo.list_recent_errors(limit=_ERROR_FEED)
    return AdminObservabilitySummary(
        today=_health_window(today),
        week=_health_window(week),
        recent_daily=recent_daily,
        recent_errors=[TurnMetricLine.model_validate(row) for row in errors],
    )


@router.get(
    "/observability/conversations/{conversation_id}",
    response_model=AdminConversationReplay,
)
async def observability_conversation(
    conversation_id: str,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    conversations: ConversationRepository = Depends(get_conversation_repo),
    messages_repo: MessageRepository = Depends(get_message_repo),
    metrics_repo: TurnMetricsRepository = Depends(get_turn_metrics_repo),
    cost_repo: CostEventRepository = Depends(get_cost_event_repo),
    journal_repo: TurnJournalRepository = Depends(get_turn_journal_repo),
    users: UserRepository = Depends(get_user_repo),
) -> AdminConversationReplay:
    """会话复盘 (观测 P2): one conversation's merged timeline — the message thread
    (bodies) overlaid with each turn's outcome/quality (turn_metrics), spend
    (cost_events), and execution spans (turn_journal), joined by trace_id /
    message_id.

    Admin-only and cross-user (any account's conversation), unlike the owner-scoped
    ``/v1/conversations/*``. The drill-down target of the 近期错误 feed: open a
    failed turn in full context (prompt + reply/error + rounds/latency + ¥ + the
    turn's tool/LLM spans).
    """
    conv = await conversations.get_by_id_unscoped(conversation_id)  # admin cross-user
    if conv is None:
        raise NotFoundError("对话不存在")

    owner = await users.get_by_id(conv.user_id)
    rows, _ = await messages_repo.list_by_conversation(conversation_id, limit=_REPLAY_MAX_MESSAGES)
    metrics = await metrics_repo.list_for_conversation(conversation_id)
    # Only the assistant reply carries a trace_id (the user prompt's is NULL), so a
    # trace overlays exactly one message — its turn's outcome/quality.
    metrics_by_trace = {m.trace_id: m for m in metrics if m.trace_id}
    cost_by_message = await cost_repo.aggregate_cost_by_message_for_conversation(conversation_id)
    # Each turn's execution spans live in turn_journal keyed by turn_id == the
    # assistant message id (NOT turn_metrics.turn_id, a separate id). Batch-load all
    # assistant turns' journals in one query (no N+1); a plain chat journaled nothing.
    journals = await journal_repo.load_map([m.id for m in rows if m.role == "assistant"])

    # The timeline is the messages ⟕ turns outer-join: a turn with a text reply rides
    # that assistant message (overlay); a text-less turn (e.g. an early hard error
    # that persisted no reply) has no message to ride, so it joins as a bare turn
    # marker — 复盘 must never hide a failure. Its spend stays in the rollup below.
    timeline: list[ReplayMessage] = []
    consumed: set[str] = set()
    for m in rows:
        overlay = metrics_by_trace.get(m.trace_id) if m.trace_id else None
        if overlay is not None:
            consumed.add(m.trace_id)
        timeline.append(
            ReplayMessage(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                trace_id=m.trace_id,
                metrics=TurnMetricLine.model_validate(overlay) if overlay else None,
                cost_total=cost_by_message.get(m.id, 0),
                spans=_project_spans(journals.get(m.id, [])),
            )
        )
    for tm in metrics:
        if not tm.trace_id or tm.trace_id in consumed:
            continue
        timeline.append(
            ReplayMessage(
                id=tm.turn_id,
                role="assistant",
                content=None,
                created_at=tm.created_at,
                trace_id=tm.trace_id,
                metrics=TurnMetricLine.model_validate(tm),
                cost_total=0,
            )
        )
    timeline.sort(key=lambda r: r.created_at)

    await record_admin_audit(
        db,
        actor_id=admin.user_id,
        action="conversation.replay",
        target_type="conversation",
        target_id=conversation_id,
        detail={
            "owner_user_id": conv.user_id,
            "turns": len(metrics),
            "messages": len(timeline),
        },
    )

    return AdminConversationReplay(
        conversation=ReplayConversation(
            id=conv.id,
            title=conv.title,
            user_id=conv.user_id,
            username=owner.username if owner else None,
            display_name=owner.display_name if owner else None,
            created_at=conv.created_at,
        ),
        messages=timeline,
        turns=len(metrics),
        errors=sum(1 for m in metrics if m.status == "error"),
        cost_total=sum(cost_by_message.values()),
        cny_per_usd=settings.cny_per_usd,
    )
