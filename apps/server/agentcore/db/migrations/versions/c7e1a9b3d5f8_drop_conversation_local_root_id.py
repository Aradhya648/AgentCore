"""drop conversations.local_root_id (文件夹即工作区: 绑定只在文件夹)

Revision ID: c7e1a9b3d5f8
Revises: a3f8c1e5b2d7
Create Date: 2026-06-17 03:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e1a9b3d5f8"
down_revision: str | None = "a3f8c1e5b2d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 文件夹即工作区重构: a workspace IS a folder, so a local-mode binding lives only on
    # the folder (folders.local_root_id, kept). A conversation no longer owns a
    # standalone binding — a 裸聊 has no workspace until it is promoted into a folder —
    # so the per-conversation column is now dead. NULL = cloud was the default, so no
    # meaningful binding is lost (any value would have duplicated the folder's anyway).
    op.drop_column("conversations", "local_root_id")


def downgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("local_root_id", sa.String(length=200), nullable=True),
    )
