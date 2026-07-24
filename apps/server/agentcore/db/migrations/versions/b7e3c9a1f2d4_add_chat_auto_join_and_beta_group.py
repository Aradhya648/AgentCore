"""add chats.auto_join + create the 内测全员群 and backfill existing users

The 内测全员群 mechanism (docs/06-规划/全员反馈群落地设计.md): one system-owned
group every user belongs to. `chats.auto_join` marks chats new accounts are
enrolled into at registration; this migration also creates the group row and
backfills all existing active users (pinned, so it surfaces at the top).

Revision ID: b7e3c9a1f2d4
Revises: a3f8c1e5b2d7
Create Date: 2026-06-17 04:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3c9a1f2d4"
down_revision: str | None = "a3f8c1e5b2d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed id for the singleton 内测全员群 so the row is recognizable and the
# downgrade can target it precisely.
BETA_GROUP_ID = "0de7a000-0000-4000-a000-000000000001"
BETA_GROUP_TITLE = "AgentCore 内测群"


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "auto_join",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Create the system-owned 内测群 (created_by NULL = system) and enroll every
    # existing active user as a pinned member. Idempotent on the membership insert
    # so a re-run can't duplicate rows. BETA_GROUP_ID is a str but chats.id /
    # chat_members.chat_id are uuid columns, and Postgres won't implicitly coerce a
    # bound varchar to uuid — so cast it explicitly at each use site.
    op.execute(
        sa.text(
            """
            INSERT INTO chats (id, type, title, auto_join, created_at, updated_at)
            VALUES (CAST(:id AS uuid), 'group', :title, true, now(), now())
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(id=BETA_GROUP_ID, title=BETA_GROUP_TITLE)
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
        ).bindparams(id=BETA_GROUP_ID)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM chat_members WHERE chat_id = CAST(:id AS uuid)"
        ).bindparams(id=BETA_GROUP_ID)
    )
    op.execute(
        sa.text("DELETE FROM chats WHERE id = CAST(:id AS uuid)").bindparams(
            id=BETA_GROUP_ID
        )
    )
    op.drop_column("chats", "auto_join")
