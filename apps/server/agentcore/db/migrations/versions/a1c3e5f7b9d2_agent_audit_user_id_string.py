"""Widen agent_audit_events.user_id to String (sidecar 'local' + non-UUID ids).

Revision ID: a1c3e5f7b9d2
Revises: d5e1f8a2c4b7
Create Date: 2026-07-11 06:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | None = "d5e1f8a2c4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "agent_audit_events",
        "user_id",
        existing_type=sa.UUID(as_uuid=False),
        type_=sa.String(length=64),
        existing_nullable=False,
        postgresql_using="user_id::text",
    )


def downgrade() -> None:
    op.alter_column(
        "agent_audit_events",
        "user_id",
        existing_type=sa.String(length=64),
        type_=sa.UUID(as_uuid=False),
        existing_nullable=False,
        postgresql_using="user_id::uuid",
    )
