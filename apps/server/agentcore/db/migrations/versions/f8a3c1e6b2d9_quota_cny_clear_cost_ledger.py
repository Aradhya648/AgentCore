"""Rename quota cost columns to CNY; clear cost ledger (人民币台账步骤 2).

Revision ID: f8a3c1e6b2d9
Revises: e7b4c2a9f1d8
Create Date: 2026-08-01 17:30:00.000000

- ``users.quota_monthly_cost_usd`` → ``quota_monthly_cost_cny``
- ``users.quota_daily_cost_usd`` → ``quota_daily_cost_cny``
- Truncate ``cost_calls`` / ``cost_events`` (dev/内测可接受清空；禁止混币种 SUM)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f8a3c1e6b2d9"
down_revision: str | None = "e7b4c2a9f1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "quota_monthly_cost_usd",
        new_column_name="quota_monthly_cost_cny",
    )
    op.alter_column(
        "users",
        "quota_daily_cost_usd",
        new_column_name="quota_daily_cost_cny",
    )
    # Ledger was nano-USD-era; wipe so nano-CNY SUM never mixes currencies.
    # cost_calls may FK into cost_events — truncate children first / CASCADE.
    op.execute("TRUNCATE TABLE cost_calls, cost_events RESTART IDENTITY CASCADE")


def downgrade() -> None:
    op.alter_column(
        "users",
        "quota_monthly_cost_cny",
        new_column_name="quota_monthly_cost_usd",
    )
    op.alter_column(
        "users",
        "quota_daily_cost_cny",
        new_column_name="quota_daily_cost_usd",
    )
    # Cleared ledger is not restored on downgrade.
