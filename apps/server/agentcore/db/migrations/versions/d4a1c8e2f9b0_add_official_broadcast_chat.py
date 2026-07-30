"""add singleton official broadcast chat + backfill members

Product notices with surface inbox/both land as one shared ``system_card`` in
this chat (全站唯一 ``type=official``). Auto-join + pinned membership mirrors
the 内测群; leave is forbidden at the service layer (unlike the beta group).

Revision ID: d4a1c8e2f9b0
Revises: c1f4a8e2b9d3
Create Date: 2026-07-30 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a1c8e2f9b0"
down_revision: str | None = "c1f4a8e2b9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed id so the row is recognizable and the downgrade can target it precisely.
OFFICIAL_CHAT_ID = "0de7a000-0000-4000-a000-000000000002"
OFFICIAL_CHAT_TITLE = "官方号"


def upgrade() -> None:
    # At most one official chat site-wide (partial unique).
    op.create_index(
        "uq_chats_official_singleton",
        "chats",
        ["type"],
        unique=True,
        postgresql_where=sa.text("type = 'official'"),
    )

    # System-owned official broadcast channel (created_by NULL). Idempotent
    # insert so a re-run can't duplicate; Postgres needs an explicit uuid cast
    # for the bound varchar id (same pattern as the 内测群 migration).
    op.execute(
        sa.text(
            """
            INSERT INTO chats (id, type, title, auto_join, created_at, updated_at)
            VALUES (CAST(:id AS uuid), 'official', :title, true, now(), now())
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(id=OFFICIAL_CHAT_ID, title=OFFICIAL_CHAT_TITLE)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO chat_members (chat_id, user_id, role, state, pinned, joined_at)
            SELECT CAST(:id AS uuid), user_id, 'member', 'accepted', true, now()
            FROM users
            WHERE status = 'active'
            ON CONFLICT (chat_id, user_id) DO NOTHING
            """
        ).bindparams(id=OFFICIAL_CHAT_ID)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM chat_messages WHERE chat_id = CAST(:id AS uuid)"
        ).bindparams(id=OFFICIAL_CHAT_ID)
    )
    op.execute(
        sa.text(
            "DELETE FROM chat_members WHERE chat_id = CAST(:id AS uuid)"
        ).bindparams(id=OFFICIAL_CHAT_ID)
    )
    op.execute(
        sa.text("DELETE FROM chats WHERE id = CAST(:id AS uuid)").bindparams(
            id=OFFICIAL_CHAT_ID
        )
    )
    op.drop_index("uq_chats_official_singleton", table_name="chats")
