"""add messages.feedback column

Revision ID: e5b9c2f7a1d4
Revises: b4d2f8a1c6e9
Create Date: 2026-07-04 03:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b9c2f7a1d4"
down_revision: str | None = "b4d2f8a1c6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 回复反馈 (点赞/点踩, 对话基础功能补齐): the user's satisfaction signal on an assistant
    # reply — "up" | "down" | NULL(未评价). Nullable with no server_default: an untouched
    # row stays NULL (未评价), distinct from an explicit rating, so existing rows need no
    # backfill.
    op.add_column("messages", sa.Column("feedback", sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "feedback")
