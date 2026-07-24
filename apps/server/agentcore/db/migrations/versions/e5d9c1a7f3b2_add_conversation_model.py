"""add conversations.model (会话级模型切换)

Revision ID: e5d9c1a7f3b2
Revises: a9c2e4f1b7d3
Create Date: 2026-07-20 07:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5d9c1a7f3b2"
down_revision: str | None = "a9c2e4f1b7d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: NULL = inherit the account's resolved model (no backfill needed).
    op.add_column(
        "conversations",
        sa.Column("model", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "model")
