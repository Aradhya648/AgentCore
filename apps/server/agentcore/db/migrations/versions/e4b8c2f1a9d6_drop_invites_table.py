"""drop invites table (退役邀请码)

Registration is open and no longer consumes invite codes; admin invite API and
ORM model are removed. Drop the legacy ``invites`` table (initial schema +
``revoked_at`` from a8f3d2c1e6b4). ``downgrade`` rebuilds the final shape
including ``revoked_at`` but does not restore deleted rows.

Revision ID: e4b8c2f1a9d6
Revises: d6f2b9a4c1e8
Create Date: 2026-08-02 20:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b8c2f1a9d6"
down_revision: str | None = "d6f2b9a4c1e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_invites_used_by"), table_name="invites")
    op.drop_index(op.f("ix_invites_created_by"), table_name="invites")
    op.drop_table("invites")


def downgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("used_by", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_invites_created_by"), "invites", ["created_by"], unique=False)
    op.create_index(op.f("ix_invites_used_by"), "invites", ["used_by"], unique=False)
