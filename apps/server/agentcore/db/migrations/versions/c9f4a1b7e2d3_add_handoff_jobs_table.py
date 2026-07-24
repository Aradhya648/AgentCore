"""add handoff_jobs table

Revision ID: c9f4a1b7e2d3
Revises: a7c4e2b9d8f1
Create Date: 2026-06-15 06:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f4a1b7e2d3"
down_revision: str | None = "a7c4e2b9d8f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Local→cloud handoff jobs (双模式工作区 P2e / e2). Purely additive new table:
    # a dispatched cloud run seeded from a local conversation's snapshot. No
    # backfill — existing data is untouched.
    op.create_table(
        "handoff_jobs",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("source_conversation_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("job_conversation_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("base_snapshot_id", sa.String(length=100), nullable=False),
        sa.Column("result_snapshot_id", sa.String(length=100), nullable=True),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'failed')",
            name="ck_handoff_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_handoff_jobs_user_id"), "handoff_jobs", ["user_id"], unique=False
    )
    op.create_index(
        "ix_handoff_jobs_source_created",
        "handoff_jobs",
        ["source_conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_handoff_jobs_source_created", table_name="handoff_jobs")
    op.drop_index(op.f("ix_handoff_jobs_user_id"), table_name="handoff_jobs")
    op.drop_table("handoff_jobs")
