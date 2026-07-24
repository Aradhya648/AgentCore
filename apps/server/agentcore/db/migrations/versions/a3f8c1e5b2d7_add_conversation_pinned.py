"""add conversations.pinned (置顶对话: 侧栏置顶排序)

Revision ID: a3f8c1e5b2d7
Revises: f5c2a8e4d9b1
Create Date: 2026-06-16 14:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f8c1e5b2d7"
down_revision: str | None = "f5c2a8e4d9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pin a conversation to the top of the sidebar / list (对话基础功能补齐). NOT
    # NULL with a server default so existing rows backfill to「未置顶」without a
    # data migration; the ORM omits the column on insert and lets the default apply
    # (the sibling ``archived`` column uses the same posture).
    op.add_column(
        "conversations",
        sa.Column(
            "pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "pinned")
