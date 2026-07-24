"""drop unused ix_conversations_memory_synced_at index

Revision ID: c5b9e3a7d2f4
Revises: e1f2a3b4c5d6
Create Date: 2026-06-15 20:05:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5b9e3a7d2f4'
down_revision: str | None = 'e1f2a3b4c5d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The single-column btree on conversations.memory_synced_at cannot serve its only
# reader (ConversationRepository.list_pending_memory_consolidation): the watermark
# appears solely inside a HAVING ``max(messages.created_at) > coalesce(
# memory_synced_at, epoch)`` and the ORDER BY is on the message aggregate, not the
# column — so no scan/sort uses it. The ORM dropped ``index=True``; realign the DB
# to match (keeps ``alembic check`` zero-drift).


def upgrade() -> None:
    op.drop_index("ix_conversations_memory_synced_at", table_name="conversations")


def downgrade() -> None:
    op.create_index(
        "ix_conversations_memory_synced_at",
        "conversations",
        ["memory_synced_at"],
    )
