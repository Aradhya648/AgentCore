"""Add cost_estimated_nano + user LLM price card / background_model.

Revision ID: d8f2a1c4e6b9
Revises: c6d2e8f1a4b9
Create Date: 2026-07-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f2a1c4e6b9"
down_revision: str | None = "c6d2e8f1a4b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cost_events",
        sa.Column(
            "cost_estimated_nano",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "cost_calls",
        sa.Column(
            "cost_estimated_nano",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_llm_keys",
        sa.Column("price_cache_hit", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "user_llm_keys",
        sa.Column("price_cache_miss", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "user_llm_keys",
        sa.Column("price_output", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "user_llm_keys",
        sa.Column("background_model", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_llm_keys", "background_model")
    op.drop_column("user_llm_keys", "price_output")
    op.drop_column("user_llm_keys", "price_cache_miss")
    op.drop_column("user_llm_keys", "price_cache_hit")
    op.drop_column("cost_calls", "cost_estimated_nano")
    op.drop_column("cost_events", "cost_estimated_nano")
