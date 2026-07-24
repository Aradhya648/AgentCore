"""add invites.revoked_at (邀请码撤销 / admin revoke)

管理员后台 用户管理 A 组: an admin can revoke an unused invite so it can no longer
register an account. Distinct from expiry (time-based) and use (consumed) — a
revoked code was deliberately retired. Nullable timestamp; NULL = not revoked.

Revision ID: a8f3d2c1e6b4
Revises: f2b9c4d7e1a3
Create Date: 2026-06-18 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f3d2c1e6b4"
down_revision: str | None = "f2b9c4d7e1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invites",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invites", "revoked_at")
