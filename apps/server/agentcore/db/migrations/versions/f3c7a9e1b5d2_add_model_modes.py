"""add model modes (custom 质量档) + per-user/-conversation selection

Revision ID: f3c7a9e1b5d2
Revises: c5b9e3a7d2f4
Create Date: 2026-06-15 12:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3c7a9e1b5d2'
down_revision: str | None = 'c5b9e3a7d2f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # User-selectable model 质量档 (llm/modes.py, D2). Purely additive:
    # - users.default_model_mode / conversations.model_mode are nullable
    #   (NULL = inherit the next level → operator default → economy), so existing
    #   rows are unaffected and need no backfill.
    # - model_modes holds user-defined custom modes; system presets stay in code.
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
    op.create_index(
        "ix_model_modes_user_id", "model_modes", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_model_modes_user_id", table_name="model_modes")
    op.drop_table("model_modes")
    op.drop_column("conversations", "model_mode")
    op.drop_column("users", "default_model_mode")
