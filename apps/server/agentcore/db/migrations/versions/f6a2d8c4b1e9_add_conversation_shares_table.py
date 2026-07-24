"""add conversation_shares table (公开只读分享链接)

Revision ID: f6a2d8c4b1e9
Revises: e7c1a9f5b3d2
Create Date: 2026-06-18 18:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a2d8c4b1e9"
down_revision: str | None = "e7c1a9f5b3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Public read-only conversation shares (对标 ChatGPT 分享链接). Purely additive new
    # table: a frozen, content-only transcript snapshot served at /shared/<id>. No
    # backfill — existing data is untouched.
    op.create_table(
        "conversation_shares",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "conversation_id", postgresql.UUID(as_uuid=False), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "title",
            sa.String(length=500),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_shares_conversation",
        "conversation_shares",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_shares_user",
        "conversation_shares",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_shares_user", table_name="conversation_shares"
    )
    op.drop_index(
        "ix_conversation_shares_conversation", table_name="conversation_shares"
    )
    op.drop_table("conversation_shares")
