"""add turn_leases table (durable RUNNING ownership for crash recover)

Revision ID: d5e1f8a2c4b7
Revises: c4e8a1b7d2f9
Create Date: 2026-07-10 23:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e1f8a2c4b7"
down_revision: str | None = "c4e8a1b7d2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Durable RUNNING lease per in-flight assistant turn. Journal is the唯一事实源;
    # this table only records owner + heartbeat so a dead process can be swept and
    # recover_turn can redrive unfinished DAG nodes. Cleared on terminal / pause / stop.
    op.create_table(
        "turn_leases",
        sa.Column("message_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column(
            "phase",
            sa.String(length=40),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index(
        op.f("ix_turn_leases_user_id"), "turn_leases", ["user_id"], unique=False
    )
    op.create_index(
        "ix_turn_leases_conversation",
        "turn_leases",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_turn_leases_heartbeat",
        "turn_leases",
        ["heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_turn_leases_heartbeat", table_name="turn_leases")
    op.drop_index("ix_turn_leases_conversation", table_name="turn_leases")
    op.drop_index(op.f("ix_turn_leases_user_id"), table_name="turn_leases")
    op.drop_table("turn_leases")
