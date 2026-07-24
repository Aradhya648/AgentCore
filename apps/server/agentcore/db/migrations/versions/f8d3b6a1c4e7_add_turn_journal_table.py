"""add turn_journal table; drop messages.runs (§8.3 Turn Journal 唯一事实源)

Revision ID: f8d3b6a1c4e7
Revises: c4f8b1d6e9a2
Create Date: 2026-06-18 01:30:00.000000

The turn's replay payload moves out of the ``messages.runs`` JSON blob into a
normalized, append-only ``turn_journal`` table (one row per execution fact, keyed
by turn_id == the assistant message id). The message's ``runs`` is projected from
it on read. Dev phase: no data backfill — old turns simply lose their replay graph
(无兼容层).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f8d3b6a1c4e7"
down_revision: str | None = "c4f8b1d6e9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The唯一事实源: a turn's ordered execution facts (run/tool/interaction events,
    # single-agent reasoning/tool 步, and a closing turn_end). PK (turn_id, seq);
    # turn_id == the assistant message_id so the projected replay rejoins its row.
    op.create_table(
        "turn_journal",
        sa.Column("turn_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("ts", sa.String(length=40), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("turn_id", "seq"),
    )
    op.create_index(
        "ix_turn_journal_conversation",
        "turn_journal",
        ["conversation_id"],
        unique=False,
    )
    # The replay payload now lives in turn_journal (projected on read); the blob is
    # gone. Dev phase, no backfill (无兼容层).
    op.drop_column("messages", "runs")


def downgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "runs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.drop_index("ix_turn_journal_conversation", table_name="turn_journal")
    op.drop_table("turn_journal")
