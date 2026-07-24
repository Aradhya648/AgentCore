"""add credentials.password_must_change (admin reset → force change on login)

Revision ID: d3a7c1e9f5b2
Revises: c2d8f1a6b4e3
Create Date: 2026-06-23 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a7c1e9f5b2"
down_revision: str | None = "c2d8f1a6b4e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credentials",
        sa.Column(
            "password_must_change",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("credentials", "password_must_change")
