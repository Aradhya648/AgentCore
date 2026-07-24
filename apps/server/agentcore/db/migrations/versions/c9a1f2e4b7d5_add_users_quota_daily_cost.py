"""add per-user daily-cost quota override to users

Revision ID: c9a1f2e4b7d5
Revises: b6f4d2a9c8e1
Create Date: 2026-07-20 06:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9a1f2e4b7d5'
down_revision: str | None = 'b6f4d2a9c8e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 日成本 quota dimension per-user override (成本配额与计费 §〇·六 F2). Purely additive:
    # NULL = inherit the config threshold (like the other quota override columns), so
    # existing rows are unaffected and no backfill is needed.
    op.add_column(
        "users", sa.Column("quota_daily_cost_usd", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "quota_daily_cost_usd")
