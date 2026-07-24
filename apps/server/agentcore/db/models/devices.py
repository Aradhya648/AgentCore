"""Mobile push device registration: PushDeviceRow."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class PushDeviceRow(Base):
    """A mobile device's push token, per user (原生推送设备注册, 认证与会话 §十).

    A Capacitor client registers its FCM token here so the backend can notify the user
    when an agent needs them (a durable plan_review / ask_user pause) while the app is
    backgrounded (SSE dropped). The ``token`` is globally unique — re-registering one
    (token rotation, or the same device under a new login) MOVES it to the current user
    (upsert on ``token``), so a token is never owned by two users. Unregistered on logout
    and pruned automatically when FCM reports it stale (push.notify).
    """

    __tablename__ = "push_devices"
    __table_args__ = (
        CheckConstraint("platform in ('ios', 'android', 'web')", name="ck_push_devices_platform"),
        # One row per device token (the upsert key); a token belongs to one user.
        UniqueConstraint("token", name="uq_push_devices_token"),
        # Fan-out lookup: a user's tokens when a push fires.
        Index("ix_push_devices_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    # The FCM registration token (long, opaque); Text since it has no fixed bound.
    token: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
