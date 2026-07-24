"""refresh_tokens session metadata columns (platform/UA/IP/family ceiling)

Revision ID: b5e9c2a7f1d4
Revises: a5c8e1f4b7d2
Create Date: 2026-07-12 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5e9c2a7f1d4"
down_revision: str | None = "a5c8e1f4b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("client_platform", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("user_agent", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("ip", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "family_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Backfill: family ceiling + last activity fall back to row creation time for
    # existing sessions so absolute-max and GC behave consistently with history.
    op.execute(
        sa.text(
            "UPDATE refresh_tokens SET last_used_at = created_at, "
            "family_started_at = created_at "
            "WHERE last_used_at IS DISTINCT FROM created_at "
            "OR family_started_at IS DISTINCT FROM created_at"
        )
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "family_started_at")
    op.drop_column("refresh_tokens", "last_used_at")
    op.drop_column("refresh_tokens", "ip")
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_column("refresh_tokens", "client_platform")
