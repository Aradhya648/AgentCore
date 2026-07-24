"""widen cost_events run/agent id columns from uuid to string

Revision ID: b3e9d4a7c1f2
Revises: a2d7f1c93b48
Create Date: 2026-06-16 05:10:00.000000

cost_events.run_id / parent_run_id / agent_id were UUID, but delegated workers
carry namespaced ids (``del_<uuid>_N``) and revisions carry ``<run>_rev2`` — not
UUIDs. Since record_runs writes a turn as one multi-row INSERT, a single non-uuid
member id aborted the whole batch (captain row included) and the caller swallowed
it to a warning: every multi-agent turn silently lost its entire cost ledger.
Widen to varchar(128) to match the actual id shape (and RunSessionRow.run_id).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e9d4a7c1f2"
down_revision: str | None = "a2d7f1c93b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("run_id", "parent_run_id", "agent_id")


def upgrade() -> None:
    # uuid → varchar(128). The unique index on run_id and nullability are preserved
    # across the type change; existing uuid values cast cleanly to text.
    for col in _COLUMNS:
        op.alter_column(
            "cost_events",
            col,
            existing_type=sa.UUID(as_uuid=False),
            type_=sa.String(length=128),
            existing_nullable=(col != "run_id"),
            postgresql_using=f"{col}::text",
        )


def downgrade() -> None:
    # varchar → uuid. Note: this fails if any non-uuid rows were written after the
    # upgrade (e.g. a delegated ``del_..._1`` member) — those ids are by definition
    # not representable as uuid, so a clean downgrade requires purging them first.
    for col in _COLUMNS:
        op.alter_column(
            "cost_events",
            col,
            existing_type=sa.String(length=128),
            type_=sa.UUID(as_uuid=False),
            existing_nullable=(col != "run_id"),
            postgresql_using=f"{col}::uuid",
        )
