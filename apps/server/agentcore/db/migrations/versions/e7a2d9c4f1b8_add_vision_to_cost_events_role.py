"""add 'vision' to cost_events.role check constraint

Revision ID: e7a2d9c4f1b8
Revises: c3e8a1f4b7d2
Create Date: 2026-06-29 15:50:00.000000

AI 协作白板 读图入账 (docs/04-前端/AI协作白板.md §九.4 Gap ②): a ``board_read`` 视觉子调用
hits a SEPARATE vision model (qwen-vl ≠ the run's DeepSeek), so its spend cannot fold into
the run's usage — it becomes its own priced ledger row under a new ``role=vision`` category,
collected onto the turn's ``message_id`` like the delegate / revise rows. Widen the role
CHECK to admit it; symmetric with a1f4c8b2e6d9 (which tightened the same constraint).

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7a2d9c4f1b8'
down_revision: str | None = 'c3e8a1f4b7d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES_OLD = "('captain', 'member', 'arena', 'title', 'memory')"
_ROLES_NEW = "('captain', 'member', 'arena', 'title', 'memory', 'vision')"


def upgrade() -> None:
    op.drop_constraint("ck_cost_events_role", "cost_events", type_="check")
    op.create_check_constraint(
        "ck_cost_events_role", "cost_events", f"role in {_ROLES_NEW}"
    )


def downgrade() -> None:
    # Remap any vision rows to 'member' before re-tightening so the old CHECK applies
    # cleanly (a vision sub-call is the closest sibling on the team payroll). Lossy by
    # design — downgrade is rare and must never fail on live billing data.
    op.execute("UPDATE cost_events SET role = 'member' WHERE role = 'vision'")
    op.drop_constraint("ck_cost_events_role", "cost_events", type_="check")
    op.create_check_constraint(
        "ck_cost_events_role", "cost_events", f"role in {_ROLES_OLD}"
    )
