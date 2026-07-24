"""add long-conversation compaction columns to conversations

Revision ID: e2c5a8f1b3d7
Revises: c1d4e7a9f3b2
Create Date: 2026-06-18 05:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c5a8f1b3d7"
down_revision: str | None = "c1d4e7a9f3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Long-conversation compaction (执行引擎架构设计 §三 长对话压缩). Purely additive:
    # all NULL = never compacted, so existing conversations just fall back to the plain
    # recent window until their first over-threshold turn triggers a fold — no backfill.
    # Not indexed: the columns are read when loading ONE conversation by id (the loader)
    # and written by the per-conversation background pass; there is no sweeper that
    # filters conversations by them (the per-turn token trigger is self-healing).
    op.add_column(
        "conversations",
        sa.Column("compaction_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("compacted_through", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("compaction_input_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "compaction_input_tokens")
    op.drop_column("conversations", "compacted_through")
    op.drop_column("conversations", "compaction_summary")
