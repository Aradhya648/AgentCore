"""merge heads: 内测全员群 + drop conversations.local_root_id

Two migrations forked off a3f8c1e5b2d7 in parallel branches and left the tree
with two heads:

  - b7e3c9a1f2d4 (add chats.auto_join + create the 内测全员群)
  - c7e1a9b3d5f8 (drop conversations.local_root_id)

They touch disjoint tables (chats/chat_members/users vs conversations), so there
is no ordering or data conflict — this is a pure merge revision that reunifies
the two branches into a single head. No schema change of its own.

Revision ID: f0a1d3c5e7b9
Revises: b7e3c9a1f2d4, c7e1a9b3d5f8
Create Date: 2026-06-17 04:20:00.000000

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f0a1d3c5e7b9"
down_revision: tuple[str, str] = ("b7e3c9a1f2d4", "c7e1a9b3d5f8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
