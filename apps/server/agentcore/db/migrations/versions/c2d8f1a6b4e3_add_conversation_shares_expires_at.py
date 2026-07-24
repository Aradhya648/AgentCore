"""add conversation_shares.expires_at (分享链接默认 TTL)

Revision ID: c2d8f1a6b4e3
Revises: b9e2f1a4c7d3
Create Date: 2026-06-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d8f1a6b4e3"
down_revision: str | None = "b9e2f1a4c7d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_shares",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_shares", "expires_at")
