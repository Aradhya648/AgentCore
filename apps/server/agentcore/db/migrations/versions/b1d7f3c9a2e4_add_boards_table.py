"""add boards table (AI 协作白板)

Revision ID: b1d7f3c9a2e4
Revises: a9d2f4c6b8e1
Create Date: 2026-06-25 22:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1d7f3c9a2e4'
down_revision: str | None = 'a9d2f4c6b8e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AI 协作白板: a spatial-JSON canvas (Excalidraw scene) per user, optionally filed
    # under a folder (folder_id NULL = ungrouped). The scene is inline JSONB (S3 offload
    # deferred for v1); ``version`` is the CAS counter for conflict-safe scene writes.
    op.create_table(
        "boards",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("folder_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("conversation_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("title", sa.String(length=500), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "scene",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
    op.create_index(op.f("ix_boards_user_id"), "boards", ["user_id"], unique=False)
    op.create_index(op.f("ix_boards_folder_id"), "boards", ["folder_id"], unique=False)
    op.create_index(
        op.f("ix_boards_conversation_id"), "boards", ["conversation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_boards_conversation_id"), table_name="boards")
    op.drop_index(op.f("ix_boards_folder_id"), table_name="boards")
    op.drop_index(op.f("ix_boards_user_id"), table_name="boards")
    op.drop_table("boards")
