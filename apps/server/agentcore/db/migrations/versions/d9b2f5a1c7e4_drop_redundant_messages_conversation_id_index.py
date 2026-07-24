"""drop redundant single-column ix_messages_conversation_id (PERF-001 follow-up)

Revision ID: d9b2f5a1c7e4
Revises: c6a3e9f1b4d8
Create Date: 2026-06-30 23:58:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9b2f5a1c7e4"
down_revision: str | None = "c6a3e9f1b4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# PERF-001 收尾: 复合 ix_messages_conversation_created (conversation_id, created_at)
# 已按最左前缀完全覆盖单列 ix_messages_conversation_id 的全部用途 —— 既服务
# 「WHERE conversation_id = ? ORDER BY created_at」的有序翻页, 也服务
# counts_for_conversations / journal load_map 的「conversation_id IN (...)」。保留单列
# 索引只会在每次消息插入 (最热写路径) 多维护一棵 btree = 纯写放大, 无任何读收益。删之。
# ORM 侧已移除 conversation_id 的 index=True, 保 ``alembic check`` 零漂移。可逆。


def upgrade() -> None:
    op.drop_index("ix_messages_conversation_id", table_name="messages")


def downgrade() -> None:
    op.create_index(
        "ix_messages_conversation_id", "messages", ["conversation_id"], unique=False
    )
