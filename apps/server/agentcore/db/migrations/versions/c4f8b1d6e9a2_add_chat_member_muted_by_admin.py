"""add chat_members.muted_by_admin (admin 禁言 for the 全员反馈群 Stage 3)

Stage 3 审核治理 (docs/06-规划/全员反馈群落地设计.md): an admin can 禁言 a group
member — they keep reading but their sends are refused (403). This is a *separate*
flag from `chat_members.muted` (the member's own notification mute) so moderation
and self-service never clobber each other.

Revision ID: c4f8b1d6e9a2
Revises: f0a1d3c5e7b9
Create Date: 2026-06-17 05:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f8b1d6e9a2"
down_revision: str | None = "f0a1d3c5e7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_members",
        sa.Column(
            "muted_by_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_members", "muted_by_admin")
