"""add user_workflows + standing_tasks.workflow_id

Revision ID: c4e8a1f2b9d7
Revises: b2f8e1c4a9d7
Create Date: 2026-07-31 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8a1f2b9d7"
down_revision: str | None = "b2f8e1c4a9d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_workflows",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        op.f("ix_user_workflows_user_id"), "user_workflows", ["user_id"], unique=False
    )
    op.create_index(
        "ix_user_workflows_user_created",
        "user_workflows",
        ["user_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "standing_tasks",
        sa.Column("workflow_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.create_index(
        op.f("ix_standing_tasks_workflow_id"),
        "standing_tasks",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_standing_tasks_workflow_id"), table_name="standing_tasks")
    op.drop_column("standing_tasks", "workflow_id")
    op.drop_index("ix_user_workflows_user_created", table_name="user_workflows")
    op.drop_index(op.f("ix_user_workflows_user_id"), table_name="user_workflows")
    op.drop_table("user_workflows")
