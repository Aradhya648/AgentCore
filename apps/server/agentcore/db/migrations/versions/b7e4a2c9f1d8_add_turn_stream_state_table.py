"""add turn_stream_state table (流式在飞通道快照 · 流式回复持久化 P0)

Revision ID: b7e4a2c9f1d8
Revises: a1c3e5f7b9d2
Create Date: 2026-07-11 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e4a2c9f1d8"
down_revision: str | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Durable projection of in-flight stream channels (UPSERT, not append). PK
    # (turn_id, channel); cleared after terminal / pause snapshot lands (P1).
    op.create_table(
        "turn_stream_state",
        sa.Column("turn_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("generation", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("turn_id", "channel"),
    )
    op.create_index(
        "ix_turn_stream_state_updated",
        "turn_stream_state",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_turn_stream_state_updated", table_name="turn_stream_state")
    op.drop_table("turn_stream_state")
