"""messages.baseline_snapshot_id — A1+ turn file-diff baseline

Revision ID: b3d9e1a7c4f2
Revises: a2c8e4f1b6d3
Create Date: 2026-07-23

代码基本功 A1+：云端回合开始 best-effort 打 labeled 工作区基线快照，id 挂在
assistant 行，供 ``GET …/messages/{id}/files/diff`` 做 before/after 只读比对。
本地 / sidecar 不写此列（桌面降级工具参数预览）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d9e1a7c4f2"
down_revision: str | None = "a2c8e4f1b6d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("baseline_snapshot_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "baseline_snapshot_id")
