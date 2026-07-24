"""make cost_events.message_id nullable for off-turn background LLM calls

Revision ID: c1d4e7a9f3b2
Revises: f8d3b6a1c4e7
Create Date: 2026-06-18 03:30:00.000000

cost_events.message_id was NOT NULL — every ledger row had to belong to an
assistant turn. Gap C bills the off-turn background LLM calls (标题生成 / 记忆
整合) too: those belong to NO turn, so they are written with message_id = NULL.
That keeps them out of a single turn's per-message 工资单 (fetched by message_id)
and out of the「请求数」(COUNT(DISTINCT message_id) ignores NULL), while still
summing into the account/conversation cost totals. Relax the column to nullable.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d4e7a9f3b2"
down_revision: str | None = "f8d3b6a1c4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "cost_events",
        "message_id",
        existing_type=sa.UUID(as_uuid=False),
        nullable=True,
    )


def downgrade() -> None:
    # NOT NULL cannot be restored while background rows (message_id IS NULL) exist;
    # they belong to no turn and are unrepresentable under the old constraint, so a
    # clean downgrade purges them first (mirrors the run_id widen downgrade note).
    op.execute("DELETE FROM cost_events WHERE message_id IS NULL")
    op.alter_column(
        "cost_events",
        "message_id",
        existing_type=sa.UUID(as_uuid=False),
        nullable=False,
    )
