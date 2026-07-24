"""add debate_user_takes table (站队/拍板 跨重载持久化, Phase 3)

Revision ID: d4e9f2a1c7b6
Revises: e7a2d9c4f1b8
Create Date: 2026-06-29 16:40:00.000000

交锋叙事直播态（前端UX设计.md §4.4 · 辩论编排设计.md §6.7）: persist a user's 站队 (stance) + 拍板 (gavel)
on a settled debate so it survives reload. One row per assistant ``message_id`` owning a
debate card (== the client ``turnId``), in its OWN table so the human's annotation never
touches the AI ``messages`` row (守 AI 中立). App-level cascade (no DB FK, per repo
convention) — cleaned with its owning message / conversation on hard-delete.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e9f2a1c7b6"
down_revision: str | None = "e7a2d9c4f1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "debate_user_takes",
        sa.Column("message_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("stance", sa.String(length=64), nullable=True),
        sa.Column("gavel", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index(
        "ix_debate_user_takes_conversation",
        "debate_user_takes",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_debate_user_takes_user",
        "debate_user_takes",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_debate_user_takes_user", table_name="debate_user_takes")
    op.drop_index("ix_debate_user_takes_conversation", table_name="debate_user_takes")
    op.drop_table("debate_user_takes")
