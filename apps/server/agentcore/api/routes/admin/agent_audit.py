"""Admin agent collaboration audit aggregates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import AdminUser, get_agent_audit_repo, get_turn_metrics_repo
from agentcore.api.schemas.agent_audit import AdminAgentAuditSummary
from agentcore.db.repositories import AgentAuditEventRepository, TurnMetricsRepository

router = APIRouter(tags=["admin"])

_AUDIT_WINDOW_DAYS = 7


@router.get("/audit/summary", response_model=AdminAgentAuditSummary)
async def agent_audit_summary(
    admin: AdminUser,
    audit_repo: AgentAuditEventRepository = Depends(get_agent_audit_repo),
    metrics_repo: TurnMetricsRepository = Depends(get_turn_metrics_repo),
) -> AdminAgentAuditSummary:
    """Platform-wide agent audit aggregates for the admin observability widget."""
    now = datetime.now(UTC)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=_AUDIT_WINDOW_DAYS - 1
    )
    summary = await audit_repo.aggregate_summary(since=since)
    audit_drops = await metrics_repo.aggregate_audit_drops_for_window(since=since)
    return AdminAgentAuditSummary(
        events=summary["events"],
        failures=summary["failures"],
        approval_timeouts=summary["approval_timeouts"],
        approval_denied=summary["approval_denied"],
        delegate_plans=summary["delegate_plans"],
        audit_drops=audit_drops,
    )
