"""add agent_audit_events + turn_metrics.audit_drops

Append-only multi-agent collaboration audit trail (Phase 1) and per-turn
degraded-write counter on turn_metrics for operator health.

Revision ID: e8f1a2b3c4d5
Revises: d7e8f9a0b1c2
Create Date: 2026-07-06 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f1a2b3c4d5"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_audit_events",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("turn_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("parent_run_id", sa.String(length=128), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_ref", sa.String(length=512), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category in ('orchestration', 'tool', 'approval', 'comm', 'state', "
            "'failure', 'permission')",
            name="ck_agent_audit_events_category",
        ),
        sa.CheckConstraint(
            "outcome in ('ok', 'denied', 'failed', 'skipped')",
            name="ck_agent_audit_events_outcome",
        ),
        sa.CheckConstraint(
            "actor_kind in ('captain', 'member', 'system')",
            name="ck_agent_audit_events_actor_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_audit_events_user_id", "agent_audit_events", ["user_id"])
    op.create_index(
        "ix_agent_audit_events_conversation_id", "agent_audit_events", ["conversation_id"]
    )
    op.create_index("ix_agent_audit_events_turn_id", "agent_audit_events", ["turn_id"])
    op.create_index("ix_agent_audit_events_trace_id", "agent_audit_events", ["trace_id"])
    op.create_index(
        "ix_agent_audit_events_execution_id", "agent_audit_events", ["execution_id"]
    )
    op.create_index("ix_agent_audit_events_run_id", "agent_audit_events", ["run_id"])
    op.create_index("ix_agent_audit_events_category", "agent_audit_events", ["category"])
    op.create_index("ix_agent_audit_events_action", "agent_audit_events", ["action"])
    op.create_index("ix_agent_audit_events_created_at", "agent_audit_events", ["created_at"])
    op.create_index(
        "ix_agent_audit_events_conversation_created",
        "agent_audit_events",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_agent_audit_events_created_category_action",
        "agent_audit_events",
        ["created_at", "category", "action"],
    )
    op.create_index(
        "ix_agent_audit_events_target_file",
        "agent_audit_events",
        ["target_type", "target_ref"],
        postgresql_where=sa.text("target_type = 'file'"),
    )

    op.add_column(
        "turn_metrics",
        sa.Column("audit_drops", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("turn_metrics", "audit_drops")
    op.drop_index("ix_agent_audit_events_target_file", table_name="agent_audit_events")
    op.drop_index(
        "ix_agent_audit_events_created_category_action", table_name="agent_audit_events"
    )
    op.drop_index("ix_agent_audit_events_conversation_created", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_created_at", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_action", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_category", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_run_id", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_execution_id", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_trace_id", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_turn_id", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_conversation_id", table_name="agent_audit_events")
    op.drop_index("ix_agent_audit_events_user_id", table_name="agent_audit_events")
    op.drop_table("agent_audit_events")
