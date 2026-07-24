"""messages.cost + drop dead tool_calls/finish_reason

Revision ID: c8d1e4f7a2b5
Revises: b7e4a2c9f1d8
Create Date: 2026-07-11 10:20:00.000000

P2 处置重对账（流式回复持久化架构 §3.5）：
- 新增 ``messages.cost``（JSONB，DERIVED 列，与 followups/title 同辙）——finalize 回写
  回合总账，重载 footer 直接用；hover 明细仍走 ``GET /v1/messages/{id}/cost``。
- 删除死列 ``messages.tool_calls``（schema 存在但无写入路径）与近死
  ``messages.finish_reason``（写路径缺失；终态 finish 走 journal turn_end /
  ``usage.status``）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d1e4f7a2b5"
down_revision: str | None = "b7e4a2c9f1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "cost",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.drop_column("messages", "tool_calls")
    op.drop_column("messages", "finish_reason")


def downgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("finish_reason", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.drop_column("messages", "cost")
