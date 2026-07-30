"""add product_notices + product_notice_dismissals

Revision ID: c1f4a8e2b9d3
Revises: b8c4e2a9f1d7
Create Date: 2026-07-30 03:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1f4a8e2b9d3"
down_revision: str | None = "b8c4e2a9f1d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_notices",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("dismiss_policy", sa.String(length=32), nullable=False),
        sa.Column("cta_label", sa.String(length=100), nullable=True),
        sa.Column("cta_url", sa.String(length=2000), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), nullable=False),
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
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity in ('critical', 'high', 'normal')",
            name="ck_product_notices_severity",
        ),
        sa.CheckConstraint(
            "surface in ('banner', 'inbox', 'both')",
            name="ck_product_notices_surface",
        ),
        sa.CheckConstraint(
            "status in ('draft', 'published', 'archived')",
            name="ck_product_notices_status",
        ),
        sa.CheckConstraint(
            "dismiss_policy in ('once', 'never')",
            name="ck_product_notices_dismiss_policy",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_notices_status", "product_notices", ["status"])

    op.create_table(
        "product_notice_dismissals",
        sa.Column("notice_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            ["product_notices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notice_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("product_notice_dismissals")
    op.drop_index("ix_product_notices_status", table_name="product_notices")
    op.drop_table("product_notices")
