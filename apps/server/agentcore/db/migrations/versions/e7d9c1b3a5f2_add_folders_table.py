"""add folders table and conversations.folder_id

Revision ID: e7d9c1b3a5f2
Revises: d4b1c2e3f5a6
Create Date: 2026-06-15 01:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7d9c1b3a5f2'
down_revision: str | None = 'd4b1c2e3f5a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # User-created conversation folders (sidebar grouping). Soft-deleted; an
    # optional local_dir is opaque metadata for now (no filesystem coupling).
    op.create_table(
        "folders",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("local_dir", sa.String(length=1000), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_folders_user_id"), "folders", ["user_id"], unique=False)

    # Conversation → folder membership (NULL = ungrouped). App-level FK only.
    op.add_column(
        "conversations",
        sa.Column("folder_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.create_index(
        op.f("ix_conversations_folder_id"),
        "conversations",
        ["folder_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_folder_id"), table_name="conversations")
    op.drop_column("conversations", "folder_id")
    op.drop_index(op.f("ix_folders_user_id"), table_name="folders")
    op.drop_table("folders")
