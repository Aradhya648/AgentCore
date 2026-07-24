"""add conversation local_root_id and local_subpath (Folder 重构)

Revision ID: b2c3d4e5f6a7
Revises: f7a3c1e9b2d5
Create Date: 2026-07-04 21:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "f7a3c1e9b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-conversation scratch workspace binding (Folder 重构: 对话级文件空间).
    # NULL local_root_id = cloud scratch under workspaces/<user>/conv/<id>/.
    op.add_column(
        "conversations",
        sa.Column("local_root_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("local_subpath", sa.String(length=400), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "local_subpath")
    op.drop_column("conversations", "local_root_id")
