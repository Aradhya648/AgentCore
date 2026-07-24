"""Cascade-delete helpers for ``agent_audit_events`` rows."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models import AgentAuditEvent, Message


async def delete_audit_for_conversation(session: AsyncSession, conversation_id: str) -> None:
    await session.execute(
        delete(AgentAuditEvent).where(AgentAuditEvent.conversation_id == conversation_id)
    )


async def delete_audit_after(
    session: AsyncSession, conversation_id: str, *, after_created_at: datetime
) -> None:
    await session.execute(
        delete(AgentAuditEvent).where(
            AgentAuditEvent.turn_id.in_(
                select(Message.id).where(
                    Message.conversation_id == conversation_id,
                    Message.created_at > after_created_at,
                )
            )
        )
    )


async def delete_audit_for_message(
    session: AsyncSession, conversation_id: str, message_id: str
) -> None:
    await session.execute(
        delete(AgentAuditEvent).where(
            AgentAuditEvent.turn_id == message_id,
            AgentAuditEvent.conversation_id == conversation_id,
        )
    )
