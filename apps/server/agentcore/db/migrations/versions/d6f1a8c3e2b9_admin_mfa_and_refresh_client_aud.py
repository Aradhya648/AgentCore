"""admin MFA table + refresh_tokens.client_aud

Revision ID: d6f1a8c3e2b9
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05 09:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6f1a8c3e2b9"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_mfa",
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_codes_hash", sa.String(length=4096), nullable=True),
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
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "client_aud",
            sa.String(length=20),
            server_default=sa.text("'product'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "client_aud")
    op.drop_table("admin_mfa")
