"""add memory_enabled to users (AI 记忆总开关)

Revision ID: a9d2f4c6b8e1
Revises: d3a7c1e9f5b2
Create Date: 2026-06-23 19:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d2f4c6b8e1"
down_revision: str | None = "d3a7c1e9f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Long-term AI memory master switch (Agent记忆与知识系统 §一). Additive; existing
    # accounts default to True (memory on, the product default). NOT NULL with a
    # server_default so the backfill is a single metadata-only write. Unindexed: the
    # only read is by user_id (PK), which already carries the flag inline.
    op.add_column(
        "users",
        sa.Column(
            "memory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "memory_enabled")
