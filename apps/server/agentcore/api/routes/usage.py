"""Cost & usage observability endpoints (单回合工资单 + 对话累计 + 账户仪表盘).

成本是产品差异点：AgentCore 是 multi-agent，单回合花销能按 Agent/角色拆开（工资单），
账户仪表盘则给窗口总额 / 额度 / 趋势。

All three reads are scoped to the authenticated user via ``cost_events.user_id``,
so a non-owner can never read another user's spend (IDOR-safe) — the message /
conversation endpoints additionally 404 or return empty rather than leaking
existence. The ledger (``cost_events``) is the truth source for real money spent
(不变量 #1); ``Message.usage`` is only a display snapshot.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from agentcore.api.cost_view import cost_breakdown, estimated_cost_breakdown, usage_breakdown
from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_cost_event_repo,
    get_user_llm_provider_repo,
    get_user_repo,
)
from agentcore.api.schemas import (
    AgentCostLine,
    ConversationCost,
    DailyCost,
    QuotaStatus,
    TurnCost,
    UsageSummary,
    UsageWindow,
)
from agentcore.billing.preference import is_free_tier_active
from agentcore.config import settings
from agentcore.conversation.quota import QuotaLimits
from agentcore.core.errors import NotFoundError
from agentcore.db.models import CostEvent
from agentcore.db.repositories import (
    ConversationRepository,
    CostEventRepository,
    UserLlmProviderRepository,
    UserRepository,
)

router = APIRouter(tags=["usage"])

# Account dashboard trend window: the last N UTC days (incl today) shown as a
# spend sparkline (§7.3D). Fixed length so the series is zero-filled and stable.
_TREND_DAYS = 7


def _sum_rows(rows: list[CostEvent]) -> tuple[dict, dict, dict, int]:
    """Roll up a turn's payroll rows into (usage, cost, estimated_cost, rounds).

    Summed in Python from the rows already fetched for the payroll (no second
    query). Billed and estimated stay on their scalar columns (never re-priced).
    """
    usage = {"input": 0, "output": 0, "reasoning": 0, "cache_hit": 0, "cache_miss": 0}
    cost = {"input": 0, "cached": 0, "output": 0, "total": 0, "pricing_source": "curated"}
    estimated = {
        "input": 0,
        "cached": 0,
        "output": 0,
        "total": 0,
        "pricing_source": "estimated",
    }
    rounds = 0
    for row in rows:
        for key in usage:
            usage[key] += int((row.tokens or {}).get(key, 0))
        row_cost = row.cost or {}
        billed_nano = int(row.cost_total_nano or 0)
        estimated_nano = int(getattr(row, "cost_estimated_nano", 0) or 0)
        if billed_nano:
            for key in ("input", "cached", "output"):
                cost[key] += int(row_cost.get(key, 0))
            cost["total"] += billed_nano
        if estimated_nano:
            for key in ("input", "cached", "output"):
                estimated[key] += int(row_cost.get(key, 0))
            estimated["total"] += estimated_nano
            if row_cost.get("pricing_source"):
                estimated["pricing_source"] = str(row_cost["pricing_source"])
        rounds += int(row.rounds or 0)
    return usage, cost, estimated, rounds


@router.get("/messages/{message_id}/cost", response_model=TurnCost)
async def get_message_cost(
    message_id: str,
    user: AuthUser,
    repo: CostEventRepository = Depends(get_cost_event_repo),
) -> TurnCost:
    """The team payroll for one assistant turn (per-Agent cost + the turn total).

    Rebuilt from the ledger by ``message_id`` (scoped to the caller), so a past
    turn's payroll replays on reload. An unknown / non-owned message yields zeros
    + an empty roster rather than 404 — it never leaks whether the id exists.
    """
    rows = list(await repo.list_for_message(message_id, user_id=user.user_id))
    agents = []
    for row in rows:
        row_cost = row.cost or {}
        billed = int(row.cost_total_nano or 0)
        estimated_nano = int(getattr(row, "cost_estimated_nano", 0) or 0)
        agents.append(
            AgentCostLine(
                run_id=row.run_id,
                agent_id=row.agent_id,
                role=row.persona or row.role,
                model=row.model,
                usage=usage_breakdown(row.tokens or {}),
                cost=cost_breakdown(
                    {
                        **({} if estimated_nano and not billed else row_cost),
                        "total": billed,
                        "input": int(row_cost.get("input", 0)) if billed else 0,
                        "cached": int(row_cost.get("cached", 0)) if billed else 0,
                        "output": int(row_cost.get("output", 0)) if billed else 0,
                        "pricing_source": str(row_cost.get("pricing_source") or "curated"),
                    }
                ),
                estimated_cost=estimated_cost_breakdown(
                    estimated_nano=estimated_nano,
                    cost=row_cost if estimated_nano else None,
                ),
                duration_ms=int(row.duration_ms or 0),
            )
        )
    usage, cost, estimated, rounds = _sum_rows(rows)
    return TurnCost(
        message_id=message_id,
        usage=usage_breakdown(usage),
        cost=cost_breakdown(cost),
        estimated_cost=estimated_cost_breakdown(cost=estimated),
        rounds=rounds,
        agents=agents,
    )


@router.get("/conversations/{conversation_id}/cost", response_model=ConversationCost)
async def get_conversation_cost(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    repo: CostEventRepository = Depends(get_cost_event_repo),
) -> ConversationCost:
    """A conversation's cumulative spend (对话累计 — the conversation-header chip).

    404 for a non-owner, consistent with the other conversation reads.
    """
    conv = await conv_repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    agg = await repo.aggregate_for_conversation(conversation_id, user_id=user.user_id)
    return ConversationCost(
        conversation_id=conversation_id,
        usage=usage_breakdown(agg["usage"]),
        cost=cost_breakdown(agg["cost"]),
        estimated_cost=estimated_cost_breakdown(cost=agg.get("estimated_cost") or {}),
        turns=agg["turns"],
    )


@router.get("/usage/summary", response_model=UsageSummary)
async def get_usage_summary(
    user: AuthUser,
    repo: CostEventRepository = Depends(get_cost_event_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    provider_repo: UserLlmProviderRepository = Depends(get_user_llm_provider_repo),
) -> UsageSummary:
    """Account dashboard: today's tokens/cost, the month's cost, the recent
    daily-cost trend, and the quota.

    Windows are bounded at the current UTC day / month start (MVP — a per-user
    timezone is a later refinement). ``recent_daily_cost`` is the last
    ``_TREND_DAYS`` UTC days (zero-filled, oldest-first) for the sparkline. Also
    carries ``cny_per_usd`` so the client formats money from the single
    server-owned rate. Per-role split lives on the turn payroll
    (``GET /messages/{id}/cost``), not this monthly account view.

    ``quota`` mirrors what ``enforce_quota`` will actually apply to this user
    (D7): per-user override columns first, else free-tier defaults on a byok
    deployment's platform-paid path (keyless free-tier riders), else global
    ``quota_*`` — so the meters never show a cap the gate wouldn't enforce.
    """
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    today = await repo.aggregate_for_window(user_id=user.user_id, since=day_start)
    month = await repo.aggregate_for_window(user_id=user.user_id, since=month_start)

    # 近 7 日趋势: zero-fill the daily map into a fixed, oldest-first series ending
    # today, so the sparkline is a stable length even for sparse spend.
    trend_start = day_start - timedelta(days=_TREND_DAYS - 1)
    daily = await repo.aggregate_daily_for_window(user_id=user.user_id, since=trend_start)
    recent_daily_cost = []
    for i in range(_TREND_DAYS):
        iso = (trend_start + timedelta(days=i)).date().isoformat()
        recent_daily_cost.append(DailyCost(date=iso, cost_total=daily.get(iso, 0)))

    account = await user_repo.get_by_id(user.user_id)

    # Mirror the gate's limit resolution: keyless users on free tier get free_tier_*
    # defaults on byok deployments; users with a BYOK provider inherit global quota_*.
    has_key = await provider_repo.count_for_user(user.user_id) > 0
    use_free_tier_defaults = (
        is_free_tier_active(has_user_key=has_key) and settings.billing_mode == "byok"
    )
    limits = (
        QuotaLimits.for_user(account, use_free_tier_defaults=use_free_tier_defaults)
        if account is not None
        else QuotaLimits.from_settings(use_free_tier_defaults=use_free_tier_defaults)
    )

    return UsageSummary(
        today=UsageWindow(
            usage=usage_breakdown(today["usage"]),
            cost=cost_breakdown(today["cost"]),
            estimated_cost=estimated_cost_breakdown(cost=today.get("estimated_cost") or {}),
            requests=today["turns"],
        ),
        month=UsageWindow(
            usage=usage_breakdown(month["usage"]),
            cost=cost_breakdown(month["cost"]),
            estimated_cost=estimated_cost_breakdown(cost=month.get("estimated_cost") or {}),
            requests=month["turns"],
        ),
        recent_daily_cost=recent_daily_cost,
        quota=QuotaStatus(
            daily_tokens=limits.daily_tokens,
            monthly_cost_nano=limits.monthly_cost_nano,
            daily_cost_nano=limits.daily_cost_nano,
            daily_requests=limits.daily_requests,
        ),
        cny_per_usd=settings.cny_per_usd,
        billing_mode=settings.billing_mode,
    )
