"""add user_llm_keys endpoint + model fields (BYOK generalization)

Revision ID: d7e8f9a0b1c2
Revises: d6f1a8c3e2b9
Create Date: 2026-07-06 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "d6f1a8c3e2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-v4-flash"


def upgrade() -> None:
    # BYOK generalization: persist the user's OpenAI-compatible endpoint + model.
    # Existing rows backfill to the prior DeepSeek-only defaults (zero interrupt).
    op.add_column(
        "user_llm_keys",
        sa.Column(
            "base_url",
            sa.String(length=500),
            server_default=sa.text(f"'{_DEFAULT_BASE_URL}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_llm_keys",
        sa.Column(
            "default_model",
            sa.String(length=200),
            server_default=sa.text(f"'{_DEFAULT_MODEL}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_llm_keys",
        sa.Column("supports_tools", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_llm_keys", "supports_tools")
    op.drop_column("user_llm_keys", "default_model")
    op.drop_column("user_llm_keys", "base_url")
