"""Product notices (全局 Notice：banner / inbox / modal)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class ProductNoticeRow(Base):
    """A product-wide notice managed by admin (draft → published → archived)."""

    __tablename__ = "product_notices"
    __table_args__ = (
        CheckConstraint(
            "severity in ('critical', 'high', 'normal')",
            name="ck_product_notices_severity",
        ),
        CheckConstraint(
            "surface in ('banner', 'inbox', 'both', 'modal')",
            name="ck_product_notices_surface",
        ),
        CheckConstraint(
            "status in ('draft', 'published', 'archived')",
            name="ck_product_notices_status",
        ),
        CheckConstraint(
            "dismiss_policy in ('once', 'never')",
            name="ck_product_notices_dismiss_policy",
        ),
        Index("ix_product_notices_status", "status"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(32))
    surface: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'draft'"))
    dismiss_policy: Mapped[str] = mapped_column(String(32))
    cta_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductNoticeDismissalRow(Base):
    """Per-user dismissal of a product notice (``dismiss_policy=once``)."""

    __tablename__ = "product_notice_dismissals"

    notice_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("product_notices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
