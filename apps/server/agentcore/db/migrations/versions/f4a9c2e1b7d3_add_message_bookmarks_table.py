"""add message_bookmarks table (消息收藏: 跨设备已收藏)

Revision ID: f4a9c2e1b7d3
Revises: e0f1a2b3c4d5
Create Date: 2026-07-08 21:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f4a9c2e1b7d3"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-user, message-level bookmarks (对话内消息 bookmark → 侧栏「已收藏」). Purely
    # additive new table — server-stored so a saved reply is reachable from any
    # device. No backfill; existing data untouched.
    op.create_table(
        "message_bookmarks",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # One bookmark per user per message; re-adding the same pair is a no-op.
        sa.UniqueConstraint(
            "user_id", "message_id", name="uq_message_bookmarks_user_message"
        ),
    )
    # The「已收藏」list read: a user's bookmarks, newest-first.
    op.create_index(
        "ix_message_bookmarks_user_created",
        "message_bookmarks",
        ["user_id", "created_at"],
        unique=False,
    )
    # Per-conversation star-state read + conversation-purge cascade.
    op.create_index(
        "ix_message_bookmarks_conversation",
        "message_bookmarks",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_message_bookmarks_conversation", table_name="message_bookmarks"
    )
    op.drop_index(
        "ix_message_bookmarks_user_created", table_name="message_bookmarks"
    )
    op.drop_table("message_bookmarks")
