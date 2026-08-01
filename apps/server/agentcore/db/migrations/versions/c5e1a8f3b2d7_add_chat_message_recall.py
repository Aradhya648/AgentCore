"""add chat_messages recalled_at / recalled_by_user_id

IM S3 撤回: soft-recall keeps the row (游标/引用不悬空), clears body for
list preview safety, fans out chat_message_updated (消息IM.md §8).

Revision ID: c5e1a8f3b2d7
Revises: b2d9e4a7c1f3
Create Date: 2026-08-01 23:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5e1a8f3b2d7"
down_revision: str | None = "b2d9e4a7c1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("recalled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "recalled_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "recalled_by_user_id")
    op.drop_column("chat_messages", "recalled_at")
