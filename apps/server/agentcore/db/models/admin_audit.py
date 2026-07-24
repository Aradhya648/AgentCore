"""Admin audit log: durable record of privileged operator actions."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class AdminAuditLog(Base):
    """One privileged action taken through the admin console or admin-gated routes.

    Append-only — operators review who did what to which resource and when. The
  ``detail`` JSON carries action-specific context (e.g. quota patch fields) without
    storing secrets (passwords are never logged).
    """

    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    actor_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False), index=True, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), index=True
    )
