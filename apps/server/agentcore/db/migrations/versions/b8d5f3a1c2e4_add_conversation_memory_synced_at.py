"""add memory_synced_at watermark to conversations

Revision ID: b8d5f3a1c2e4
Revises: d8e2f4a6c1b3
Create Date: 2026-06-15 16:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d5f3a1c2e4'
down_revision: str | None = 'd8e2f4a6c1b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Offline long-term-memory consolidation watermark (Agent记忆与知识系统 §1.5).
    # Purely additive: NULL = never consolidated, so existing conversations are
    # picked up by the first sweep with no backfill. Indexed because the sweeper
    # backstop filters/sorts conversations by it each pass.
    op.add_column(
        "conversations",
        sa.Column("memory_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversations_memory_synced_at",
        "conversations",
        ["memory_synced_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_memory_synced_at", table_name="conversations")
    op.drop_column("conversations", "memory_synced_at")
