"""standing_tasks L2a: webhook trigger columns

Revision ID: a3d9f2e8b1c4
Revises: f2a8c4e1b7d9
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3d9f2e8b1c4"
down_revision: str | tuple[str, ...] | None = "f2a8c4e1b7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "standing_tasks",
        sa.Column(
            "trigger_kind",
            sa.String(length=16),
            server_default=sa.text("'schedule'"),
            nullable=False,
        ),
    )
    op.add_column(
        "standing_tasks",
        sa.Column("webhook_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "standing_tasks",
        sa.Column("webhook_secret_hash", sa.String(length=64), nullable=True),
    )
    op.alter_column("standing_tasks", "cron", existing_type=sa.String(length=64), nullable=True)
    op.alter_column(
        "standing_tasks",
        "next_run_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.create_index(
        "ix_standing_tasks_webhook_id",
        "standing_tasks",
        ["webhook_id"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_standing_tasks_trigger_kind",
        "standing_tasks",
        "trigger_kind in ('schedule', 'webhook')",
    )
    # Rebuild due index to prefer schedule rows (claim filter also checks trigger_kind).
    op.drop_index("ix_standing_tasks_due", table_name="standing_tasks")
    op.create_index(
        "ix_standing_tasks_due",
        "standing_tasks",
        ["trigger_kind", "enabled", "next_run_at"],
        unique=False,
    )

    op.add_column(
        "standing_task_runs",
        sa.Column(
            "trigger_source",
            sa.String(length=16),
            server_default=sa.text("'schedule'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_standing_task_runs_trigger_source",
        "standing_task_runs",
        "trigger_source in ('schedule', 'webhook', 'manual')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_standing_task_runs_trigger_source", "standing_task_runs", type_="check")
    op.drop_column("standing_task_runs", "trigger_source")

    op.drop_index("ix_standing_tasks_due", table_name="standing_tasks")
    op.create_index(
        "ix_standing_tasks_due",
        "standing_tasks",
        ["enabled", "next_run_at"],
        unique=False,
    )
    op.drop_constraint("ck_standing_tasks_trigger_kind", "standing_tasks", type_="check")
    op.drop_index("ix_standing_tasks_webhook_id", table_name="standing_tasks")
    # Webhook rows may have NULL cron / next_run_at — fill before restoring NOT NULL.
    op.execute(
        "UPDATE standing_tasks SET cron = '0 9 * * *' WHERE cron IS NULL"
    )
    op.execute(
        "UPDATE standing_tasks SET next_run_at = now() WHERE next_run_at IS NULL"
    )
    op.alter_column(
        "standing_tasks",
        "next_run_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column("standing_tasks", "cron", existing_type=sa.String(length=64), nullable=False)
    op.drop_column("standing_tasks", "webhook_secret_hash")
    op.drop_column("standing_tasks", "webhook_id")
    op.drop_column("standing_tasks", "trigger_kind")
