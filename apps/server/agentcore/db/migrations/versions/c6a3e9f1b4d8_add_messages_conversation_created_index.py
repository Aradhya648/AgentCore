"""add messages (conversation_id, created_at) composite index (PERF-001)

Revision ID: c6a3e9f1b4d8
Revises: f1d8c3a6b9e4
Create Date: 2026-06-30 23:55:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6a3e9f1b4d8"
down_revision: str | None = "f1d8c3a6b9e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 全 App 最高频读形是「按时序翻页一个对话」: 每个消息读路径
# (MessageRepository.list_latest / list_before / list_after / list_recent /
#  list_recent_after / list_all_for_conversation / delete_after / latest_created_at)
# 都是 ``WHERE conversation_id = ? ORDER BY created_at [LIMIT ?]``。仅有的单列
# ``ix_messages_conversation_id`` 能定位行、却不能提供有序性 —— 命中后仍要对整段匹配
# 行做内存排序 (随对话变长而变贵)。复合 (conversation_id, created_at) 让这些查询走
# 索引有序扫描 + LIMIT 提前停 (项目审计-成本性能专项 PERF-001)。
#
# 纯增量: 单列 ``ix_messages_conversation_id`` 暂留 (本迁移不删, 保零回归); 复合索引
# 落地后它已被左前缀包含、可在后续单独评估删冗。ORM 侧已在 Message.__table_args__ 同步
# 登记本索引, 保 ``alembic check`` 零漂移。
#
# 注: 用普通 ``create_index`` (与既有索引迁移一致)。生产大表宜走 CREATE INDEX
# CONCURRENTLY 避免写锁, 但开发期表小、且 Alembic 默认事务内无法 CONCURRENTLY,
# 故此处保持简单一致。


def upgrade() -> None:
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created", table_name="messages")
