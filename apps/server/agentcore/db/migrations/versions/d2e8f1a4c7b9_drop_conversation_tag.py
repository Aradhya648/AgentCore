"""drop conversations.tag column (对话自动标签 removed)

Revision ID: d2e8f1a4c7b9
Revises: c8d1e4f7a2b5
Create Date: 2026-07-12 02:30:00.000000

Product decision: conversation type classification
(code_review / research / writing / analysis) is removed end-to-end.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2e8f1a4c7b9"
down_revision: str | None = "c8d1e4f7a2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TAG_CHECK = "tag IS NULL OR tag IN ('code_review', 'research', 'writing', 'analysis')"


def upgrade() -> None:
    op.drop_constraint("ck_conversations_tag_enum", "conversations", type_="check")
    op.drop_column("conversations", "tag")


def downgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("tag", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_conversations_tag_enum",
        "conversations",
        _TAG_CHECK,
    )
