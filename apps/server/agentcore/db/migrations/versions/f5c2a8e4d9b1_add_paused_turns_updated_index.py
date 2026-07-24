"""add paused_turns.updated_at index (结构化挂起 2b TTL sweep)

Revision ID: f5c2a8e4d9b1
Revises: e4a1d9c2b7f3
Create Date: 2026-06-16 10:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5c2a8e4d9b1"
down_revision: str | None = "e4a1d9c2b7f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The 7-day idle TTL sweep (runtime/suspension_retention.py) scans paused turns by
    # last-touch — delete rows whose updated_at < cutoff — so index that column to keep
    # the periodic sweep cheap as the table grows.
    op.create_index(
        "ix_paused_turns_updated", "paused_turns", ["updated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_paused_turns_updated", table_name="paused_turns")
