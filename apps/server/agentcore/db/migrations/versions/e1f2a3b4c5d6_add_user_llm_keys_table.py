"""add user_llm_keys table (BYOK)

Revision ID: e1f2a3b4c5d6
Revises: a1f4c8b2e6d9
Create Date: 2026-06-15 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: str | None = 'a1f4c8b2e6d9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # BYOK: one DeepSeek API key per user (config.billing_mode "byok"). The key is
    # stored only as AES-256-GCM ciphertext (api_key_enc); endpoint/model are fixed
    # by server config so they are intentionally not persisted here. Additive — no
    # backfill (users without a row simply have no key configured yet).
    op.create_table(
        "user_llm_keys",
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("api_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'unchecked'"),
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
        sa.CheckConstraint(
            "status in ('unchecked', 'active', 'error')",
            name="ck_user_llm_keys_status",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_llm_keys")
