"""add turn_metrics table

Revision ID: f2b9c4d7e1a3
Revises: a4f1c8e2b6d9
Create Date: 2026-06-18 08:00:00.000000

Per-turn 运营观测 telemetry for the admin 观测看板 (one row per completed assistant
turn). The operator-facing counterpart of the dev firehose (logs/dev.jsonl): it
persists the same outcome/quality fields the turn already logs at
chat.turn_complete / chat.resume_complete (status / finish_reason / rounds /
duration / delegated / workers / tokens), so the dashboard aggregates them with
indexed SQL instead of scanning the JSONL file — which prod's stdout-only logging
posture (settings.log_file default "") may never even write. Compact +
non-duplicative: money stays in cost_events and message text in messages, joined
here by trace_id. Distinct from turn_journal (the replay event stream).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b9c4d7e1a3"
down_revision: str | None = "a4f1c8e2b6d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_metrics",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("turn_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "kind", sa.String(length=16), server_default=sa.text("'turn'"), nullable=False
        ),
        sa.Column(
            "status", sa.String(length=8), server_default=sa.text("'ok'"), nullable=False
        ),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("rounds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "delegated", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("workers", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status in ('ok', 'error')", name="ck_turn_metrics_status"),
        sa.CheckConstraint("kind in ('turn', 'resume')", name="ck_turn_metrics_kind"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_turn_metrics_turn_id"), "turn_metrics", ["turn_id"], unique=False
    )
    op.create_index(
        op.f("ix_turn_metrics_conversation_id"),
        "turn_metrics",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_turn_metrics_user_id"), "turn_metrics", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_turn_metrics_trace_id"), "turn_metrics", ["trace_id"], unique=False
    )
    op.create_index(
        "ix_turn_metrics_created", "turn_metrics", ["created_at"], unique=False
    )
    op.create_index(
        "ix_turn_metrics_conversation_created",
        "turn_metrics",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_turn_metrics_conversation_created", table_name="turn_metrics")
    op.drop_index("ix_turn_metrics_created", table_name="turn_metrics")
    op.drop_index(op.f("ix_turn_metrics_trace_id"), table_name="turn_metrics")
    op.drop_index(op.f("ix_turn_metrics_user_id"), table_name="turn_metrics")
    op.drop_index(op.f("ix_turn_metrics_conversation_id"), table_name="turn_metrics")
    op.drop_index(op.f("ix_turn_metrics_turn_id"), table_name="turn_metrics")
    op.drop_table("turn_metrics")
