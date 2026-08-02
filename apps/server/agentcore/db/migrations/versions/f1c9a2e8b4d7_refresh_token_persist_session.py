"""refresh_tokens.persist_session for session-cookie login

Revision ID: f1c9a2e8b4d7
Revises: e4b8c2f1a9d6
Create Date: 2026-08-02 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c9a2e8b4d7"
down_revision: str | None = "e4b8c2f1a9d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "persist_session",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "persist_session")
