"""Platform-wide usage board (全站用量看板)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from agentcore.api.cost_view import cost_breakdown, estimated_cost_breakdown, usage_breakdown
from agentcore.api.dependencies import AdminUser, get_cost_event_repo
from agentcore.api.routes.admin._shared import _TREND_DAYS
from agentcore.api.schemas import (
    AdminUsageSummary,
    AdminUserCostLine,
    DailyCost,
    ModelCostLine,
    RoleCostLine,
    UsageWindow,
)
from agentcore.config import settings
from agentcore.db.repositories import CostEventRepository

router = APIRouter(tags=["admin"])

# 全站看板 Top-N spenders shown in the by-user payroll (the long tail isn't
# actionable for ops).
_TOP_USERS = 20


@router.get("/usage/summary", response_model=AdminUsageSummary)
async def usage_summary(
    admin: AdminUser,
    repo: CostEventRepository = Depends(get_cost_event_repo),
) -> AdminUsageSummary:
    """全站用量看板: platform-wide today / month totals, the Top spenders by user
    (工资单 by user), and the 7-day platform trend.

    The cross-user counterpart of ``GET /v1/usage/summary`` — same windows (bounded
    at the current UTC day / month start, MVP), but aggregated over *every* account
    instead of scoped to the caller. ``billing_mode`` lets the client frame cost
    honestly: in "byok" these totals are the sum of each user's spend on their own
    DeepSeek key (not platform-paid).
    """
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    today = await repo.aggregate_for_window(since=day_start)
    month = await repo.aggregate_for_window(since=month_start)
    month_by_user = await repo.aggregate_by_user_for_window(since=month_start, limit=_TOP_USERS)
    month_by_role = await repo.aggregate_by_role_for_window(since=month_start)
    month_by_model = await repo.aggregate_by_model_for_window(since=month_start)

    # 近 7 日趋势: zero-fill the daily map into a fixed, oldest-first series ending
    # today so the sparkline is a stable length even for sparse spend.
    trend_start = day_start - timedelta(days=_TREND_DAYS - 1)
    daily = await repo.aggregate_daily_for_window(since=trend_start)
    recent_daily_cost = []
    for i in range(_TREND_DAYS):
        iso = (trend_start + timedelta(days=i)).date().isoformat()
        recent_daily_cost.append(DailyCost(date=iso, cost_total=daily.get(iso, 0)))

    return AdminUsageSummary(
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
        month_by_user=[
            AdminUserCostLine(
                user_id=row["user_id"],
                username=row["username"],
                display_name=row["display_name"],
                cost_total=int(row["cost_total"]),
                turns=int(row["turns"]),
            )
            for row in month_by_user
        ],
        month_by_role=[
            RoleCostLine(
                role=row["role"],
                cost_total=int(row["cost_total"]),
                cost_estimated_total=int(row.get("cost_estimated_total", 0) or 0),
                turns=int(row["turns"]),
            )
            for row in month_by_role
        ],
        month_by_model=[
            ModelCostLine(
                model=row["model"],
                calls=int(row["calls"]),
                tokens_total=int(row["tokens_total"]),
                cost_total=int(row["cost_total"]),
                cost_estimated_total=int(row.get("cost_estimated_total", 0) or 0),
            )
            for row in month_by_model
        ],
        recent_daily_cost=recent_daily_cost,
        cny_per_usd=settings.cny_per_usd,
        billing_mode=settings.billing_mode,
    )
