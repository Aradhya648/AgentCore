"""add conversation tag column (对话自动标签)

Revision ID: a7c3e9f1b2d4
Revises: f4a9c2e1b7d3
Create Date: 2026-07-09 02:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f1b2d4"
down_revision: str | None = "f4a9c2e1b7d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TAG_CHECK = (
    "tag IS NULL OR tag IN ('code_review', 'research', 'writing', 'analysis')"
)


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("tag", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_conversations_tag_enum",
        "conversations",
        _TAG_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint("ck_conversations_tag_enum", "conversations", type_="check")
    op.drop_column("conversations", "tag")
