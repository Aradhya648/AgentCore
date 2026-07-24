"""tighten cost_events.role check constraint (drop synthesis)

Revision ID: a1f4c8b2e6d9
Revises: b8d5f3a1c2e4
Create Date: 2026-06-15 19:45:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1f4c8b2e6d9'
down_revision: str | None = 'b8d5f3a1c2e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 'synthesis' was an early zero-cost pseudo-run role; the CEO captain root run
# absorbed it, so no live code path writes it anymore (see runtime/costing.py).
# Drop it from the allowed set — remap any historical stray rows to 'captain'
# first so the tightened CHECK applies cleanly.
_ROLES_NEW = "('captain', 'member', 'arena', 'title', 'memory')"
_ROLES_OLD = "('captain', 'member', 'synthesis', 'arena', 'title', 'memory')"


def upgrade() -> None:
    op.execute("UPDATE cost_events SET role = 'captain' WHERE role = 'synthesis'")
    op.drop_constraint("ck_cost_events_role", "cost_events", type_="check")
    op.create_check_constraint(
        "ck_cost_events_role", "cost_events", f"role in {_ROLES_NEW}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_cost_events_role", "cost_events", type_="check")
    op.create_check_constraint(
        "ck_cost_events_role", "cost_events", f"role in {_ROLES_OLD}"
    )
