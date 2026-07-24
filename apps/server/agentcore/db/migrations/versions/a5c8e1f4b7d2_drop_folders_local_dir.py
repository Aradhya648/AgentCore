"""drop folders.local_dir (项目即工作区: path label removed)

Revision ID: a5c8e1f4b7d2
Revises: f4a8c2e6b9d1
Create Date: 2026-07-12 07:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5c8e1f4b7d2"
down_revision: str | None = "f4a8c2e6b9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("folders", "local_dir")


def downgrade() -> None:
    op.add_column(
        "folders",
        sa.Column("local_dir", sa.String(length=1000), nullable=True),
    )
