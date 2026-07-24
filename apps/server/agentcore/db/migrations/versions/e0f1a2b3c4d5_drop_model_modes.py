"""drop model modes (质量档 retired: unified user model / BYOK)

Revision ID: e0f1a2b3c4d5
Revises: a1b2c3d4e5f7
Create Date: 2026-07-08 20:30:00.000000

The user-selectable model 质量档 feature is permanently retired (replaced by the
unified per-user model / BYOK). This drops its now-dead schema — the ``model_modes``
table plus the ``users.default_model_mode`` / ``conversations.model_mode`` selection
columns — so the ORM (single source of truth) and the DB stay drift-free. The
downgrade re-creates the same additive schema (all nullable / defaulted, so no
backfill either way).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_model_modes_user_id", table_name="model_modes")
    op.drop_table("model_modes")
    op.drop_column("conversations", "model_mode")
    op.drop_column("users", "default_model_mode")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("default_model_mode", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("model_mode", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "model_modes",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "assignments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_modes_user_id", "model_modes", ["user_id"], unique=False)
