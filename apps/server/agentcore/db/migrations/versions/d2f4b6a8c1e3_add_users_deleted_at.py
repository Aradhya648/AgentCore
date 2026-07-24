"""add deleted_at to users (self-service account deletion)

Revision ID: d2f4b6a8c1e3
Revises: a8f3d2c1e6b4
Create Date: 2026-06-18 16:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2f4b6a8c1e3"
down_revision: str | None = "a8f3d2c1e6b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Self-service account deletion (注销账户). Purely additive: NULL = live account,
    # a timestamp = user-initiated soft delete (the row is also anonymized +
    # status='disabled' so it can't authenticate). No backfill — existing accounts
    # are live (NULL). Unindexed: no query filters by it yet (deletion anonymizes
    # username/email + disables status, which is what the auth/login paths check).
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
