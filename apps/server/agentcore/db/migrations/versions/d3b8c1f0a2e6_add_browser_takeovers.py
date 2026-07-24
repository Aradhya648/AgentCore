"""add browser_takeovers (L3 团队浏览器 M2 接管留档 · D17)

Revision ID: d3b8c1f0a2e6
Revises: c9a1f2e4b7d5
Create Date: 2026-07-20 07:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd3b8c1f0a2e6'
down_revision: str | None = 'c9a1f2e4b7d5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Durable audit trail of user-takeover episodes (内置浏览器与Agent浏览器提案.md · D17).
    # Purely additive new table; no backfill. Never stores frame/key/text content.
    op.create_table(
        "browser_takeovers",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_browser_takeovers_user_id", "browser_takeovers", ["user_id"], unique=False
    )
    op.create_index(
        "ix_browser_takeovers_conversation_started",
        "browser_takeovers",
        ["conversation_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_browser_takeovers_conversation_started", table_name="browser_takeovers")
    op.drop_index("ix_browser_takeovers_user_id", table_name="browser_takeovers")
    op.drop_table("browser_takeovers")
