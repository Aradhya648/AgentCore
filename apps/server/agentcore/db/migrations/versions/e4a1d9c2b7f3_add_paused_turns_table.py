"""add paused_turns table (结构化挂起 durable resume: turn 级落盘 + /resume)

Revision ID: e4a1d9c2b7f3
Revises: d1e3f5a7c9b2
Create Date: 2026-06-16 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e4a1d9c2b7f3"
down_revision: str | None = "d1e3f5a7c9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Durable snapshot of a turn that suspended at a plan_review checkpoint, so it
    # survives a process restart / client disconnect and POST .../resume can rebuild
    # and continue it. PK is the turn's assistant message_id (a UUID minted by the
    # pipeline); the frame JSONB holds the full resumable state (plan + completed
    # seed + CEO context + journal). Deleted on resume / live resolve / timeout.
    op.create_table(
        "paused_turns",
        sa.Column("message_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "frame",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index(
        op.f("ix_paused_turns_user_id"), "paused_turns", ["user_id"], unique=False
    )
    op.create_index(
        "ix_paused_turns_conversation",
        "paused_turns",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_paused_turns_conversation", table_name="paused_turns")
    op.drop_index(op.f("ix_paused_turns_user_id"), table_name="paused_turns")
    op.drop_table("paused_turns")
