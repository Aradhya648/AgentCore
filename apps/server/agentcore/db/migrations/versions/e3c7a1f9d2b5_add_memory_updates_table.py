"""add memory_updates table (记忆更新对话内可见)

Revision ID: e3c7a1f9d2b5
Revises: d4e9f2a1c7b6
Create Date: 2026-06-30 20:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3c7a1f9d2b5"
down_revision: str | None = "d4e9f2a1c7b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One offline consolidation pass's applied changes, anchored to the conversation that
    # triggered it (Agent记忆与知识系统 §1.6 实时提示). Backs the conversation-tail
    # 「记忆已更新」card. App-level cascade (no DB FK, per repo convention): dropped with
    # its conversation on hard-delete. Additive — existing conversations simply have none.
    op.create_table(
        "memory_updates",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The conversation-tail card read (newest-first) + whole-conversation cascade delete.
    op.create_index(
        "ix_memory_updates_conversation",
        "memory_updates",
        ["conversation_id", "created_at"],
    )
    # Account-注销 cascade + future per-user「记忆动态」feed.
    op.create_index(
        "ix_memory_updates_user",
        "memory_updates",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_updates_user", table_name="memory_updates")
    op.drop_index("ix_memory_updates_conversation", table_name="memory_updates")
    op.drop_table("memory_updates")
