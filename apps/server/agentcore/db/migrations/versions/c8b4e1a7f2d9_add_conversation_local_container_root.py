"""add local_container_root_id to conversations (工作区对称化 D1a)

Revision ID: c8b4e1a7f2d9
Revises: a3e5c7d9b2f4
Create Date: 2026-06-20 08:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8b4e1a7f2d9"
down_revision: str | None = "a3e5c7d9b2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Desktop's intended local container root, captured at conversation creation
    # (工作区对称化 D1a). NULL = cloud intent (web / mobile /「云端临时对话」). A 裸聊's
    # first file write — by an Agent turn OR a panel op — lazily promotes it into a
    # *local* workspace under this root instead of a cloud folder, so both promotion
    # paths agree on locality regardless of which writes first. Purely additive,
    # nullable, no backfill — existing conversations stay cloud-intent.
    op.add_column(
        "conversations",
        sa.Column("local_container_root_id", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "local_container_root_id")
