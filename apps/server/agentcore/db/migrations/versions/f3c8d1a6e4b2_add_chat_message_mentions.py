"""add chat_messages.mentions frozen JSONB

IM S2 @人/@所有人: store the structured mentions list at send time
(消息IM.md §8). Empty list when the message has no mentions.

Revision ID: f3c8d1a6e4b2
Revises: e2b7c4a9f1d8
Create Date: 2026-07-30 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3c8d1a6e4b2"
down_revision: str | None = "e2b7c4a9f1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "mentions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "mentions")
