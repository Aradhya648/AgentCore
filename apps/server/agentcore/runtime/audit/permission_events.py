"""Out-of-turn audit writes (session permission changes, etc.)."""

from __future__ import annotations

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.db.base import telemetry_session_factory
from agentcore.db.repositories import AgentAuditEventRepository
from agentcore.runtime.audit.projector import project_permission_axes_changed

logger = get_logger(__name__)


async def record_permission_axes_change(
    *,
    user_id: str,
    conversation_id: str,
    previous: dict,
    next_axes: dict,
) -> None:
    """Best-effort append of a permission.axes_changed row (category=permission).

    Uses ``conversation_id`` as the synthetic ``turn_id`` so the security ledger
    can list mode switches alongside turn audits without a schema change.
    """
    if previous == next_axes:
        return
    draft = project_permission_axes_changed(previous=previous, next_axes=next_axes)
    try:
        async with telemetry_session_factory() as db:
            repo = AgentAuditEventRepository(db)
            seq = await repo.next_seq_for_turn(turn_id=conversation_id)
            await repo.append(
                user_id=user_id,
                conversation_id=conversation_id,
                turn_id=conversation_id,
                trace_id=None,
                seq=seq,
                category=draft.category,
                action=draft.action,
                actor_kind=draft.actor_kind,
                outcome=draft.outcome,
                target_type=draft.target_type,
                target_ref=draft.target_ref,
                detail=draft.detail,
                execution_id=None,
                run_id=None,
                parent_run_id=None,
            )
    except Exception as e:  # noqa: BLE001 — never block the permission API
        logger.warning(
            "audit.permission_axes_change_failed",
            conversation_id=conversation_id,
            error=str(e),
            event_id=new_id(),
        )
