"""Add missing ix_cost_calls_trace_id (ORM already declares index=True).

Revision ID: a2c8e4f1b6d3
Revises: e6b2d9f1a7c4
Create Date: 2026-07-21 18:40:00.000000

``cost_calls.trace_id`` gained ``index=True`` in the ORM after the table was
created without that index. Live ``alembic check`` then reported a drift.
Table is small in current prod (~hundreds of rows); plain CREATE INDEX is fine.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2c8e4f1b6d3"
down_revision: str | None = "e6b2d9f1a7c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_cost_calls_trace_id", "cost_calls", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cost_calls_trace_id", table_name="cost_calls")
