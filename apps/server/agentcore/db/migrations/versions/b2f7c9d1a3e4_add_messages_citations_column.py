"""add messages.citations column

Revision ID: b2f7c9d1a3e4
Revises: 67481901f9af
Create Date: 2026-06-14 19:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2f7c9d1a3e4'
down_revision: str | None = '67481901f9af'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-message web sources (list of {url, title, snippet, site}) for source
    # cards. server_default backfills existing rows to '[]' so it is never NULL.
    op.add_column(
        "messages",
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "citations")
