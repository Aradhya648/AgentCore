"""add conversation_external_grants (W3 区外授权对话级持久)

Revision ID: c7e2a9f1b4d8
Revises: a3d9f2e8b1c4
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e2a9f1b4d8"
down_revision: str | tuple[str, ...] | None = "a3d9f2e8b1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Conversation-scoped external directory grants (alias / root_id / mode).
    # Desktop holds absolute paths; server never stores them. App-level FK only.
    op.create_table(
        "conversation_external_grants",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("root_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'readonly'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "alias",
            name="uq_conversation_external_grants_conv_alias",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "root_id",
            name="uq_conversation_external_grants_conv_root",
        ),
    )
    op.create_index(
        "ix_conversation_external_grants_conversation",
        "conversation_external_grants",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_external_grants_conversation",
        table_name="conversation_external_grants",
    )
    op.drop_table("conversation_external_grants")
