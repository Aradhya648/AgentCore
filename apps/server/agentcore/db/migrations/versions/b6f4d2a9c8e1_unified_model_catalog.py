"""unified model catalog: conversations.model_origin + drop users.billing_preference

Revision ID: b6f4d2a9c8e1
Revises: e5d9c1a7f3b2
Create Date: 2026-07-20 08:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6f4d2a9c8e1"
down_revision: str | None = "e5d9c1a7f3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("model_origin", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_conversations_model_origin",
        "conversations",
        "model_origin is null or model_origin in ('platform', 'byok')",
    )
    op.drop_constraint("ck_users_billing_preference", "users", type_="check")
    op.drop_column("users", "billing_preference")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "billing_preference",
            sa.String(length=20),
            server_default=sa.text("'byok'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_billing_preference",
        "users",
        "billing_preference in ('platform', 'byok')",
    )
    op.drop_constraint("ck_conversations_model_origin", "conversations", type_="check")
    op.drop_column("conversations", "model_origin")
