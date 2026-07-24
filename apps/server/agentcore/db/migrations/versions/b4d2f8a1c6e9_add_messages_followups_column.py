"""add messages.followups column

Revision ID: b4d2f8a1c6e9
Revises: d9b2f5a1c7e4
Create Date: 2026-07-04 00:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4d2f8a1c6e9'
down_revision: str | None = 'd9b2f5a1c7e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 回合级「下一步推荐」chips (下一步推荐, DERIVED 持久化): the post-turn World B narrow
    # task's quick-reply suggestions, minted alongside the title after message_end and
    # written back onto the assistant row. Persisted (twin of conversations.title) so
    # reopening a conversation replays the last turn's chips. server_default backfills
    # existing rows to '[]' so the column is never NULL.
    op.add_column(
        "messages",
        sa.Column(
            "followups",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "followups")
