"""drop conversations.instructions column

Revision ID: b8e4f2a1c9d6
Revises: a7c3e9f1b2d4
Create Date: 2026-07-09 08:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e4f2a1c9d6"
down_revision: str | None = "a7c3e9f1b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("conversations", "instructions")


def downgrade() -> None:
    op.add_column("conversations", sa.Column("instructions", sa.Text(), nullable=True))
