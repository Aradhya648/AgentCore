"""add messages.attachments column

Revision ID: 67481901f9af
Revises: bfb6ea2824ae
Create Date: 2026-06-14 18:13:23.065393

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '67481901f9af'
down_revision: str | None = 'bfb6ea2824ae'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-message user attachments metadata (name/path/truncated). server_default
    # backfills existing rows to '[]' so the column is never NULL.
    op.add_column(
        "messages",
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "attachments")
