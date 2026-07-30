"""add chat_messages.reply_to frozen snapshot JSONB

IM S1 reply-quote: store a lightweight preview at send time so later recall
of the target message still leaves a readable quote (消息IM.md §8).

Revision ID: e2b7c4a9f1d8
Revises: d4a1c8e2f9b0
Create Date: 2026-07-30 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2b7c4a9f1d8"
down_revision: str | None = "d4a1c8e2f9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("reply_to", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "reply_to")
