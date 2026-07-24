"""add unique (turn_id, seq) on agent_audit_events for at-least-once dedupe

Revision ID: c4e8a1b7d2f9
Revises: b8e4f2a1c9d6
Create Date: 2026-07-10 19:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8a1b7d2f9"
down_revision: str | None = "b8e4f2a1c9d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop duplicate (turn_id, seq) rows keeping the earliest by created_at / id
    # so the unique constraint can be applied on existing data.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY turn_id, seq
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM agent_audit_events
        )
        DELETE FROM agent_audit_events
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    op.create_unique_constraint(
        "uq_agent_audit_events_turn_seq",
        "agent_audit_events",
        ["turn_id", "seq"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_audit_events_turn_seq",
        "agent_audit_events",
        type_="unique",
    )
