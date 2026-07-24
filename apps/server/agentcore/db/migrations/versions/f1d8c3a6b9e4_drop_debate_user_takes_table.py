"""drop debate_user_takes table (移除辩论用户拍板/站队持久化)

Revision ID: f1d8c3a6b9e4
Revises: e3c7a1f9d2b5
Create Date: 2026-06-30 20:30:00.000000

辩论的「用户拍板」(gavel) 功能整体移除、「站队」(stance) 降级为纯前端会话内态（不再落库），故其
专用持久化表 ``debate_user_takes`` (原 d4e9f2a1c7b6 建) 不再有任何读写方，连同应用层级联一并删除。
是一张纯用户侧标注表（与 AI ``messages`` 物理隔离），删除不影响任何 AI 内容 / 裁决。
``downgrade`` 重建表与索引（与原迁移同形），但不恢复已删数据。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1d8c3a6b9e4"
down_revision: str | None = "e3c7a1f9d2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_debate_user_takes_user", table_name="debate_user_takes")
    op.drop_index("ix_debate_user_takes_conversation", table_name="debate_user_takes")
    op.drop_table("debate_user_takes")


def downgrade() -> None:
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
