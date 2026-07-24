"""add billing_preference to users (per-user platform vs BYOK)

Revision ID: a1b2c3d4e5f7
Revises: f9a1b2c3d4e5
Create Date: 2026-07-08 01:10:00.000000

"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "f9a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_MODE = os.environ.get("BILLING_MODE", "byok")
if _DEFAULT_MODE not in ("platform", "byok"):
    _DEFAULT_MODE = "byok"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "billing_preference",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_MODE}'"),
        ),
    )
    op.create_check_constraint(
        "ck_users_billing_preference",
        "users",
        "billing_preference in ('platform', 'byok')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_billing_preference", "users", type_="check")
    op.drop_column("users", "billing_preference")
