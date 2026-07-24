"""add conversations.permission_preset (会话级权限模式)

Revision ID: c6d2e8f1a4b9
Revises: b5e9c2a7f1d4
Create Date: 2026-07-14 17:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d2e8f1a4b9"
down_revision: str | None = "b5e9c2a7f1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "permission_preset",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'workspace'"),
        ),
    )
    op.create_check_constraint(
        "ck_conversations_permission_preset",
        "conversations",
        "permission_preset in ('observe', 'workspace', 'full_trust')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_conversations_permission_preset", "conversations", type_="check")
    op.drop_column("conversations", "permission_preset")
