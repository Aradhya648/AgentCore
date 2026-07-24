"""cost_calls detail table + cost_events.persona

Revision ID: f4a8c2e6b9d1
Revises: e3b7c2a9f1d4
Create Date: 2026-07-12 04:30:00.000000

Billing topology unification (成本配额 §三): per-call detail rows are the
authority; ``cost_events`` remains the per-run materialized view product
surfaces read. ``persona`` carries human-facing role labels (调研员 / CEO / …)
so dashboard payroll can group beyond captain/member buckets. No historical
backfill — old rows keep persona NULL; read side falls back to ``role``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a8c2e6b9d1"
down_revision: str | None = "e3b7c2a9f1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = "('captain', 'member', 'arena', 'title', 'memory', 'vision')"


def upgrade() -> None:
    op.add_column(
        "cost_events",
        sa.Column("persona", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "cost_calls",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("parent_run_id", sa.String(length=128), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("persona", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column(
            "tokens",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "cost",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "cost_total_nano",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"role in {_ROLES}", name="ck_cost_calls_role"),
        sa.UniqueConstraint("call_id", name="uq_cost_calls_call_id"),
    )
    op.create_index("ix_cost_calls_user_created", "cost_calls", ["user_id", "created_at"])
    op.create_index("ix_cost_calls_message", "cost_calls", ["message_id"])
    op.create_index("ix_cost_calls_run", "cost_calls", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_cost_calls_run", table_name="cost_calls")
    op.drop_index("ix_cost_calls_message", table_name="cost_calls")
    op.drop_index("ix_cost_calls_user_created", table_name="cost_calls")
    op.drop_table("cost_calls")
    op.drop_column("cost_events", "persona")
