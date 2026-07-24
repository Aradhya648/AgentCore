"""add collaboration-quality columns to turn_metrics

Revision ID: c3e8a1f4b7d2
Revises: b1d7f3c9a2e4
Create Date: 2026-06-29 11:30:00.000000

学·度量 闸门 (docs/06-规划/远期规划.md §2.4): per-turn 协作质量 signals, the
operator面 counterpart of the offline log_stats 方向盘. Four counters the turn already
surfaces at chat.turn_complete (off the delegate/revise tool roll-ups), persisted so the
admin 观测看板 can aggregate them with indexed SQL instead of scanning logs/dev.jsonl
(which prod's stdout-only posture may never write). All NOT NULL default 0, so existing
rows + plain single-agent turns read as zeros — byte-for-byte unchanged behavior.

  boundary_yields — 受监督边界让出次数 (首计划存活率 = delegated turns whose value is 0)
  scope_signals   — escalate kind=scope count (漂移率)
  revises         — 定向唤回 次数 (返工率 的一半; contract 重试 stays a dev-log signal)
  escalations     — total worker→captain escalations (协作信号)

空转·早收 (the 4th doc metric) reads off the existing finish_reason — no new column.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e8a1f4b7d2"
down_revision: str | None = "b1d7f3c9a2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("boundary_yields", "scope_signals", "revises", "escalations")


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column(
            "turn_metrics",
            sa.Column(col, sa.Integer(), server_default=sa.text("0"), nullable=False),
        )


def downgrade() -> None:
    for col in reversed(_COLUMNS):
        op.drop_column("turn_metrics", col)
