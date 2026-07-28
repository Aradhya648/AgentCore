"""browser_takeovers.session_id — link takeover audit to a live tab

Revision ID: e5b2a8c1d4f7
Revises: a4f7c2e9b1d8
Create Date: 2026-07-28

Additive nullable column: new takeover rows may store the registry ``session_id``
(hex UUID string). Older rows keep NULL. No uniqueness on (conversation_id, session_id).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b2a8c1d4f7"
down_revision: str | None = "a4f7c2e9b1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_takeovers",
        sa.Column("session_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_browser_takeovers_session_id",
        "browser_takeovers",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_browser_takeovers_session_id", table_name="browser_takeovers")
    op.drop_column("browser_takeovers", "session_id")
