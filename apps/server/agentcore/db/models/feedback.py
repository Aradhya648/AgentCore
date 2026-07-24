"""User feedback for beta testing (内测反馈)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class FeedbackRow(Base):
    """A user's feedback entry (bug report, feature request, etc.)."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "category in ('bug', 'feature', 'improvement', 'other')",
            name="ck_feedback_category",
        ),
        CheckConstraint(
            "status in ('open', 'acknowledged', 'resolved', 'closed')",
            name="ck_feedback_status",
        ),
        Index("ix_feedback_user", "user_id"),
        Index("ix_feedback_status", "status"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    page_context: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), server_default=text("'open'"))
    admin_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
