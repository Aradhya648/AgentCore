"""add users.autonomy_policy (能力授权三档)

Revision ID: e3b7c2a9f1d4
Revises: d2e8f1a4c7b9
Create Date: 2026-07-12 03:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b7c2a9f1d4"
down_revision: str | None = "d2e8f1a4c7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "autonomy_policy",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'first_grant'"),
        ),
    )
    op.create_check_constraint(
        "ck_users_autonomy_policy",
        "users",
        "autonomy_policy in ('always_ask', 'first_grant', 'full_auto')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_autonomy_policy", "users", type_="check")
    op.drop_column("users", "autonomy_policy")
