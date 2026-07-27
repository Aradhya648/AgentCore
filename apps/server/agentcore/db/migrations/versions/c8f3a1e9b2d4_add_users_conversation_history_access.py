"""add conversation_history_access to users (跨会话对话日志访问闸)

Revision ID: c8f3a1e9b2d4
Revises: d7a1c4e9f2b8
Create Date: 2026-07-27 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f3a1e9b2d4"
down_revision: str | None = "d7a1c4e9f2b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Privacy gate for Worker search/read of past conversation transcripts
    # (跨会话对话日志访问定案). Orthogonal to memory_enabled. Default ON.
    op.add_column(
        "users",
        sa.Column(
            "conversation_history_access",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "conversation_history_access")
