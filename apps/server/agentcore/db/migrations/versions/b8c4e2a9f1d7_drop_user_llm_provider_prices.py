"""Drop BYOK user_llm_providers self-filled unit price columns.

Revision ID: b8c4e2a9f1d7
Revises: c7e2a9f1b4d8
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c4e2a9f1d7"
down_revision: str | tuple[str, ...] | None = "c7e2a9f1b4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("user_llm_providers", "price_output")
    op.drop_column("user_llm_providers", "price_cache_miss")
    op.drop_column("user_llm_providers", "price_cache_hit")


def downgrade() -> None:
    op.add_column(
        "user_llm_providers",
        sa.Column("price_cache_hit", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "user_llm_providers",
        sa.Column("price_cache_miss", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "user_llm_providers",
        sa.Column("price_output", sa.String(length=40), nullable=True),
    )
