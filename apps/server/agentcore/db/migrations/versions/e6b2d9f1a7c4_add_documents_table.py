"""add documents table (Document 子系统第一期载体)

Revision ID: e6b2d9f1a7c4
Revises: f1e7a3d9c2b4
Create Date: 2026-07-20 19:40:00.000000

The single ``documents`` content tree that carries user rules, AI-maintained long-term
memory, and ordinary documents as ONE table (Agent记忆与知识系统 §五 / §5.7；核心接口定义
§6.2「文件模型单表设计」). Memory migrates off ``FileMemoryStore`` into ``ai_maintained=true``
``rule`` nodes here; user rules are ``ai_maintained=false`` ``rule`` nodes. ``kind`` × ``role``
× ``apply_mode`` are CheckConstraint-bounded; ``parent_id`` is the intra-tree parent and
``folder_id`` the injection scope (NULL = global). No DB FK (app-level refs, §6.2); soft delete.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b2d9f1a7c4"
down_revision: str | None = "f1e7a3d9c2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("parent_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("folder_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "kind", sa.String(length=20), server_default=sa.text("'document'"), nullable=False
        ),
        sa.Column(
            "role", sa.String(length=20), server_default=sa.text("'general'"), nullable=False
        ),
        sa.Column(
            "ai_maintained", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "apply_mode", sa.String(length=20), server_default=sa.text("'always'"), nullable=False
        ),
        sa.Column("name", sa.String(length=500), server_default=sa.text("''"), nullable=False),
        sa.Column("content", sa.Text(), server_default=sa.text("''"), nullable=False),
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
        sa.CheckConstraint(
            "kind in ('folder', 'document', 'upload', 'base')", name="ck_documents_kind"
        ),
        sa.CheckConstraint(
            "role in ('rule', 'general', 'attachment')", name="ck_documents_role"
        ),
        sa.CheckConstraint(
            "apply_mode in ('always', 'conditional', 'on_demand')",
            name="ck_documents_apply_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_documents_user_parent", "documents", ["user_id", "parent_id"], unique=False
    )
    op.create_index(
        "ix_documents_user_folder", "documents", ["user_id", "folder_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_documents_user_folder", table_name="documents")
    op.drop_index("ix_documents_user_parent", table_name="documents")
    op.drop_table("documents")
