"""add per-user quota overrides to users

Revision ID: a7c4e2b9d8f1
Revises: f1a2b3c4d5e6
Create Date: 2026-06-15 05:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c4e2b9d8f1'
down_revision: str | None = 'f1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-user quota overrides (成本配额与计费.md §一, 决策④). Purely additive:
    # is_unlimited defaults false (everyone keeps the global config thresholds), and
    # the three override columns are NULL = inherit config — so no backfill is
    # needed and existing rows are unaffected.
    op.add_column(
        "users",
        sa.Column(
            "is_unlimited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users", sa.Column("quota_daily_tokens", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "users", sa.Column("quota_monthly_cost_usd", sa.Float(), nullable=True)
    )
    op.add_column(
        "users", sa.Column("quota_daily_requests", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "quota_daily_requests")
    op.drop_column("users", "quota_monthly_cost_usd")
    op.drop_column("users", "quota_daily_tokens")
    op.drop_column("users", "is_unlimited")
