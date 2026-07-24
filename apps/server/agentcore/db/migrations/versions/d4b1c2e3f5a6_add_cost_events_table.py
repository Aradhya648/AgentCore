"""add cost_events table

Revision ID: d4b1c2e3f5a6
Revises: c3a8e5d2f1b6
Create Date: 2026-06-15 00:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4b1c2e3f5a6'
down_revision: str | None = 'c3a8e5d2f1b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-run cost ledger (append-only). One row per Run = one Agent's
    # participation in a turn (captain root included). Single source of truth for
    # money spent; rebuilt into the team payroll by querying on message_id, and
    # SUMmed by (user_id, created_at) for the account dashboard / quota.
    op.create_table(
        "cost_events",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("message_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("parent_run_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("agent_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column(
            "tokens",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cost",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cost_total_nano",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("rounds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role in ('captain', 'member', 'synthesis', 'arena', 'title', 'memory')",
            name="ck_cost_events_role",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        op.f("ix_cost_events_user_id"), "cost_events", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_cost_events_conversation_id"),
        "cost_events",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_cost_events_user_created",
        "cost_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_cost_events_message", "cost_events", ["message_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_cost_events_message", table_name="cost_events")
    op.drop_index("ix_cost_events_user_created", table_name="cost_events")
    op.drop_index(op.f("ix_cost_events_conversation_id"), table_name="cost_events")
    op.drop_index(op.f("ix_cost_events_user_id"), table_name="cost_events")
    op.drop_table("cost_events")
