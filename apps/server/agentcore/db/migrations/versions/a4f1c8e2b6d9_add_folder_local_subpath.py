"""add local_subpath to folders (工作区对称化 D1a)

Revision ID: a4f1c8e2b6d9
Revises: e2c5a8f1b3d7
Create Date: 2026-06-18 04:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4f1c8e2b6d9"
down_revision: str | None = "e2c5a8f1b3d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sub-path within a folder's bound local root (工作区对称化 D1a). NULL = the
    # folder is the root itself (an explicitly-added local project, current
    # behavior). A non-empty segment marks a per-conversation workspace lazily
    # promoted under a shared container root. Purely additive, nullable, no
    # backfill — every existing folder stays at its root.
    op.add_column(
        "folders",
        sa.Column("local_subpath", sa.String(length=400), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("folders", "local_subpath")
