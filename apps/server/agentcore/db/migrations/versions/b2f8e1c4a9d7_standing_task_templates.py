"""Standing task system templates (daily conversation review).

Revision ID: b2f8e1c4a9d7
Revises: a6e2f9b4c1d8
Create Date: 2026-07-31 02:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2f8e1c4a9d7"
down_revision: str | None = "a6e2f9b4c1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "standing_tasks",
        sa.Column("template_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "standing_tasks",
        sa.Column(
            "template_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "uq_standing_tasks_user_template",
        "standing_tasks",
        ["user_id", "template_key"],
        unique=True,
        postgresql_where=sa.text("template_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_standing_tasks_user_template",
        table_name="standing_tasks",
        postgresql_where=sa.text("template_key IS NOT NULL"),
    )
    op.drop_column("standing_tasks", "template_config")
    op.drop_column("standing_tasks", "template_key")
