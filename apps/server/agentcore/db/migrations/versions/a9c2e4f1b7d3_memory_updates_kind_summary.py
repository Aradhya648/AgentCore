"""memory_updates: kind + summary (two-layer memory)

Revision ID: a9c2e4f1b7d3
Revises: f3a7c1e9b2d4
Create Date: 2026-07-19 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c2e4f1b7d3"
down_revision: str | None = "f3a7c1e9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Two-layer memory: episodic (session summary tip) vs semantic (diff card).
    # Existing rows are semantic consolidations from the old one-shot path.
    op.add_column(
        "memory_updates",
        sa.Column(
            "kind",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'semantic'"),
        ),
    )
    op.add_column(
        "memory_updates",
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_updates", "summary")
    op.drop_column("memory_updates", "kind")
