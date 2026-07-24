"""add avatar_key to users (头像上传)

Revision ID: e7c1a9f5b3d2
Revises: d2f4b6a8c1e3
Create Date: 2026-06-18 17:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c1a9f5b3d2"
down_revision: str | None = "d2f4b6a8c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Avatar (头像) object-storage key: NULL = no avatar. Purely additive; existing
    # accounts start with no avatar (NULL). The bytes live in object storage
    # (storage/assets.py), only the key is persisted here. Unindexed: the only
    # lookup is by user_id (PK) which already carries the key inline.
    op.add_column(
        "users",
        sa.Column("avatar_key", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_key")
