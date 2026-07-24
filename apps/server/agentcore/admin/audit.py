"""Admin audit recording helper (操作审计 write path)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.repositories.admin_audit import AdminAuditRepository


async def record_admin_audit(
    session: AsyncSession,
    *,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Best-effort append of one privileged action. Call after the mutation succeeds."""
    await AdminAuditRepository(session).record(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
