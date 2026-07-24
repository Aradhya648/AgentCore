"""add run_sessions table (留人 跨进程落盘: 乙 热修 P3)

Revision ID: a2d7f1c93b48
Revises: f3c7a9e1b5d2
Create Date: 2026-06-16 05:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a2d7f1c93b48'
down_revision: str | None = 'f3c7a9e1b5d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Durable backstop for the in-memory 留人 roster: a finished worker's recoverable
    # session (transcript + spec) persisted so 定向唤回 (revise) still hits after a
    # restart or memory eviction. run_id is a namespaced string (del_<uuid>_N /
    # <run>_revN), NOT a UUID, so it is the string PK directly. Pruned by a 7-day
    # idle TTL sweep on updated_at (its index serves that scan).
    op.create_table(
        "run_sessions",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "spec",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "content", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "recall_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        op.f("ix_run_sessions_conversation_id"),
        "run_sessions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_run_sessions_updated", "run_sessions", ["updated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_run_sessions_updated", table_name="run_sessions")
    op.drop_index(
        op.f("ix_run_sessions_conversation_id"), table_name="run_sessions"
    )
    op.drop_table("run_sessions")
