"""Admin action audit trail (操作审计)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from agentcore.api.dependencies import AdminUser, get_admin_audit_repo
from agentcore.api.schemas import AdminAuditLogLine, AdminAuditLogListResponse
from agentcore.db.repositories import AdminAuditRepository

router = APIRouter(tags=["admin"])


@router.get("/audit-logs", response_model=AdminAuditLogListResponse)
async def list_audit_logs(
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    action: str | None = Query(None, max_length=64),
    actor_id: str | None = Query(None),
    audit_repo: AdminAuditRepository = Depends(get_admin_audit_repo),
) -> AdminAuditLogListResponse:
    """操作审计： privileged actions taken through the admin console, newest first.

    Filters: ``action`` exact match (e.g. ``user.update``), ``actor_id`` pin one
    operator. Append-only — each row is who did what to which resource and when.
    """
    rows, total = await audit_repo.list_page(
        page=page,
        page_size=page_size,
        action=action,
        actor_id=actor_id,
    )
    return AdminAuditLogListResponse(
        data=[
            AdminAuditLogLine(
                id=log.id,
                actor_id=log.actor_id,
                actor_username=username,
                action=log.action,
                target_type=log.target_type,
                target_id=log.target_id,
                detail=log.detail,
                created_at=log.created_at,
            )
            for log, username in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
