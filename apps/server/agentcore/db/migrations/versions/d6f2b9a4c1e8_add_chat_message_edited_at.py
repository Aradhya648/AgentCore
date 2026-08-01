"""add chat_messages edited_at

IM S4 编辑: stamp edited_at on content rewrite within 15-minute window;
fans out chat_message_updated (消息IM.md §8).

Revision ID: d6f2b9a4c1e8
Revises: c5e1a8f3b2d7
Create Date: 2026-08-02 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6f2b9a4c1e8"
down_revision: str | None = "c5e1a8f3b2d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "edited_at")
