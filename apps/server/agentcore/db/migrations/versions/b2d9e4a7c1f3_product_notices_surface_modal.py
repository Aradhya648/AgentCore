"""Allow product_notices.surface = modal.

Revision ID: b2d9e4a7c1f3
Revises: f8a3c1e6b2d9
Create Date: 2026-08-01 18:30:00.000000

Widen ``ck_product_notices_surface`` to
``('banner', 'inbox', 'both', 'modal')``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2d9e4a7c1f3"
down_revision: str | None = "f8a3c1e6b2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_product_notices_surface", "product_notices", type_="check")
    op.create_check_constraint(
        "ck_product_notices_surface",
        "product_notices",
        "surface in ('banner', 'inbox', 'both', 'modal')",
    )


def downgrade() -> None:
    # Reject rows that would violate the old constraint before recreating it.
    op.execute("UPDATE product_notices SET surface = 'both' WHERE surface = 'modal'")
    op.drop_constraint("ck_product_notices_surface", "product_notices", type_="check")
    op.create_check_constraint(
        "ck_product_notices_surface",
        "product_notices",
        "surface in ('banner', 'inbox', 'both')",
    )
