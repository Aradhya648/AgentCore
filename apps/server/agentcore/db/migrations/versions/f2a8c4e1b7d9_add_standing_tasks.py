"""add standing_tasks + standing_task_runs (站立任务 L1)

Merges divergent heads then creates the two new tables.

Revision ID: f2a8c4e1b7d9
Revises: b7e3c9a1f2d4, c7e1a9b3d5f8, e5b2a8c1d4f7
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a8c4e1b7d9"
down_revision: str | tuple[str, ...] | None = (
    "b7e3c9a1f2d4",
    "c7e1a9b3d5f8",
    "e5b2a8c1d4f7",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standing_tasks",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("folder_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("cron", sa.String(length=64), nullable=False),
        sa.Column(
            "permission_axes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'{"file_write":"session","command":"kickoff","team_kickoff":"rules"}\'::jsonb'
            ),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversation_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_standing_tasks_user_id"), "standing_tasks", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_standing_tasks_folder_id"), "standing_tasks", ["folder_id"], unique=False
    )
    op.create_index(
        op.f("ix_standing_tasks_conversation_id"),
        "standing_tasks",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_standing_tasks_due",
        "standing_tasks",
        ["enabled", "next_run_at"],
        unique=False,
    )
    op.create_index(
        "ix_standing_tasks_user_created",
        "standing_tasks",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "standing_task_runs",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("standing_task_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("user_message_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('running', 'succeeded', 'failed', 'awaiting_user')",
            name="ck_standing_task_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_standing_task_runs_standing_task_id"),
        "standing_task_runs",
        ["standing_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_standing_task_runs_user_id"),
        "standing_task_runs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_standing_task_runs_user_created",
        "standing_task_runs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_standing_task_runs_task_created",
        "standing_task_runs",
        ["standing_task_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_standing_task_runs_user_status",
        "standing_task_runs",
        ["user_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_standing_task_runs_user_status", table_name="standing_task_runs")
    op.drop_index("ix_standing_task_runs_task_created", table_name="standing_task_runs")
    op.drop_index("ix_standing_task_runs_user_created", table_name="standing_task_runs")
    op.drop_index(op.f("ix_standing_task_runs_user_id"), table_name="standing_task_runs")
    op.drop_index(
        op.f("ix_standing_task_runs_standing_task_id"), table_name="standing_task_runs"
    )
    op.drop_table("standing_task_runs")

    op.drop_index("ix_standing_tasks_user_created", table_name="standing_tasks")
    op.drop_index("ix_standing_tasks_due", table_name="standing_tasks")
    op.drop_index(op.f("ix_standing_tasks_conversation_id"), table_name="standing_tasks")
    op.drop_index(op.f("ix_standing_tasks_folder_id"), table_name="standing_tasks")
    op.drop_index(op.f("ix_standing_tasks_user_id"), table_name="standing_tasks")
    op.drop_table("standing_tasks")
