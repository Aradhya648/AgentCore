"""add conversations.instructions column

Revision ID: f7a3c1e9b2d5
Revises: e5b9c2f7a1d4
Create Date: 2026-07-04 03:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a3c1e9b2d5"
down_revision: str | None = "e5b9c2f7a1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 对话级自定义指令 (per-conversation custom instructions): a user-authored directive
    # injected into this conversation's system prompt (above soft long-term memory).
    # Nullable with no server_default — an untouched conversation stays NULL (no custom
    # instructions), so existing rows need no backfill.
    op.add_column("conversations", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "instructions")
