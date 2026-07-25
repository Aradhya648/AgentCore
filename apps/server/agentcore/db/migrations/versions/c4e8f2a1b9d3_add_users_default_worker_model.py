"""users.default_worker_(provider_id, model) — optional Worker default pointer

Revision ID: c4e8f2a1b9d3
Revises: b3d9e1a7c4f2
Create Date: 2026-07-25

账号级可选「子 Worker 默认模型」指针（空 = 跟随主对话模型），对齐
default_chat_* / default_background_* 形态。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8f2a1b9d3"
down_revision: str | None = "b3d9e1a7c4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "default_worker_provider_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("default_worker_model", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "default_worker_model")
    op.drop_column("users", "default_worker_provider_id")
