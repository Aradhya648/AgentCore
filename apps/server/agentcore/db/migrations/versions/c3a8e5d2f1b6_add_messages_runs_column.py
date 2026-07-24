"""add messages.runs column

Revision ID: c3a8e5d2f1b6
Revises: b2f7c9d1a3e4
Create Date: 2026-06-14 22:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3a8e5d2f1b6'
down_revision: str | None = 'b2f7c9d1a3e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-message multi-agent execution journal (the turn's ordered run/tool
    # events) for replaying a past turn's team graph on reload. NULL on messages
    # with no delegation (user / single-agent), so the column is nullable with no
    # server_default (absence is meaningful, unlike the citations '[]' backfill).
    op.add_column(
        "messages",
        sa.Column(
            "runs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "runs")
