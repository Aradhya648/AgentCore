"""add messages.evidence_ledger column

Revision ID: e8c2a4f1b6d9
Revises: a5c8e2f1b4d7
Create Date: 2026-07-18 08:20:00.000000

引用即出处 P1 · Q4/Q9：独立 turn 级台账通道 DERIVED 落库列。与 citations 池正交；
server_default '[]' 回填存量行，legacy 缺字段不炸。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8c2a4f1b6d9"
down_revision: str | None = "a5c8e2f1b4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "evidence_ledger",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "evidence_ledger")
