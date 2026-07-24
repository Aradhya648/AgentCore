"""add trace_id to messages / cost_events / run_sessions for log join

Revision ID: d1e3f5a7c9b2
Revises: b3e9d4a7c1f2
Create Date: 2026-06-16 15:10:00.000000

Joins the persisted turn data back to the runtime log trace (logs/dev.jsonl):
``trace_id`` is the one-per-interaction correlation key (core/log_context.py),
log-only until now. Stamping it on the assistant message, the per-run cost rows,
and recoverable worker sessions lets a DB row resolve to its full log chain (and
survives log truncation). Additive + nullable + backward-compatible: existing
rows stay NULL (untraced); only new turns carry it. 32-hex string (uuid4().hex),
not a DB-format uuid, so a plain String column — matching how it reads in logs.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e3f5a7c9b2"
down_revision: str | None = "b3e9d4a7c1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.add_column("cost_events", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.add_column("run_sessions", sa.Column("trace_id", sa.String(length=32), nullable=True))
    # Indexed where the join is queried (log trace_id → DB rows). run_sessions is
    # looked up by its run_id PK, so it needs no trace_id index.
    op.create_index("ix_messages_trace_id", "messages", ["trace_id"])
    op.create_index("ix_cost_events_trace_id", "cost_events", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_cost_events_trace_id", table_name="cost_events")
    op.drop_index("ix_messages_trace_id", table_name="messages")
    op.drop_column("run_sessions", "trace_id")
    op.drop_column("cost_events", "trace_id")
    op.drop_column("messages", "trace_id")
