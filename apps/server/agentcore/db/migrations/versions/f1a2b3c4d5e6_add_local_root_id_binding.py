"""add local_root_id binding to folders and conversations

Revision ID: f1a2b3c4d5e6
Revises: e7d9c1b3a5f2
Create Date: 2026-06-15 05:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: str | None = 'e7d9c1b3a5f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Local-mode binding (双模式工作区 §七): the desktop FS root a workspace is
    # bound to. NULL = cloud (the default), so this is a purely additive, nullable
    # column with no backfill — every existing folder / conversation stays on the
    # server backend. Stored as a plain string (opaque desktop handle), not a UUID.
    op.add_column(
        "folders",
        sa.Column("local_root_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("local_root_id", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "local_root_id")
    op.drop_column("folders", "local_root_id")
