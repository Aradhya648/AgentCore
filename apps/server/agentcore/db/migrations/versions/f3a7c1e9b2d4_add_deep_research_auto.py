"""add conversations.deep_research_auto + auto-debate count

Revision ID: f3a7c1e9b2d4
Revises: e8c2a4f1b6d9
Create Date: 2026-07-18 23:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a7c1e9b2d4"
down_revision: str | None = "e8c2a4f1b6d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "deep_research_auto",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "deep_research_auto_debate_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "deep_research_auto_debate_count")
    op.drop_column("conversations", "deep_research_auto")
