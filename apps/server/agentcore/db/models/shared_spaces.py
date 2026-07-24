"""Shared space models (多人共享空间, docs/02-架构/双模式工作区.md §十一):
space / members / change events.

Independent of Folder (项目) and IM chats — a file-only collaboration container
addressed as ``shared:<space_id>``. Member roles are their own enum (owner /
editor / viewer), not IM's owner/admin/member.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class SharedSpace(Base):
    __tablename__ = "shared_spaces"

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    # App-level FK → users. Owner is always a member with role=owner.
    owner_user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )


class SharedSpaceMember(Base):
    __tablename__ = "shared_space_members"
    __table_args__ = (
        CheckConstraint(
            "role in ('owner', 'editor', 'viewer')",
            name="ck_shared_space_members_role",
        ),
        CheckConstraint(
            "state in ('accepted', 'pending')",
            name="ck_shared_space_members_state",
        ),
        Index("ix_shared_space_members_user_id", "user_id"),
    )

    space_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'")
    )
    invited_by: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SharedSpaceEvent(Base):
    """Durable change log for attribution (谁 / 谁的 Agent 改了什么)."""

    __tablename__ = "shared_space_events"
    __table_args__ = (
        Index("ix_shared_space_events_space_created", "space_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    space_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    # Who performed the action (human user id). Agent writes still attribute to
    # the member whose session ran the Agent.
    actor_user_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False), nullable=True)
    # ``user`` | ``agent`` — whether the actor typed or their Agent wrote.
    actor_via: Mapped[str] = mapped_column(
        String(20), default="user", server_default=text("'user'")
    )
    # e.g. file_written / file_deleted / member_invited / member_removed / …
    action: Mapped[str] = mapped_column(String(40))
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
