"""Drop AutonomyPolicy.write_code; default less_interrupt; axes default session/auto/skip/ask.

Revision ID: a6e2f9b4c1d8
Revises: f3c8d1a6e4b2
Create Date: 2026-07-31 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6e2f9b4c1d8"
down_revision: str | None = "f3c8d1a6e4b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_AXES = (
    '{"file_write":"session","command":"auto","team_kickoff":"skip","host":"ask"}'
)


def upgrade() -> None:
    op.drop_constraint("ck_users_autonomy_policy", "users", type_="check")
    op.execute(
        "UPDATE users SET autonomy_policy = 'less_interrupt' "
        "WHERE autonomy_policy = 'write_code'"
    )
    op.alter_column(
        "users",
        "autonomy_policy",
        existing_type=sa.String(length=32),
        server_default=sa.text("'less_interrupt'"),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_users_autonomy_policy",
        "users",
        "autonomy_policy in ('cautious', 'less_interrupt', 'managed')",
    )

    op.alter_column(
        "conversations",
        "permission_axes",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{_DEFAULT_AXES}'::jsonb"),
        existing_nullable=False,
    )
    op.alter_column(
        "standing_tasks",
        "permission_axes",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{_DEFAULT_AXES}'::jsonb"),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Dev-only: restore write_code enum/default; do not invent prior row values.
    _legacy_axes = '{"file_write":"session","command":"kickoff","team_kickoff":"rules"}'
    op.alter_column(
        "standing_tasks",
        "permission_axes",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{_legacy_axes}'::jsonb"),
        existing_nullable=False,
    )
    op.alter_column(
        "conversations",
        "permission_axes",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{_legacy_axes}'::jsonb"),
        existing_nullable=False,
    )
    op.drop_constraint("ck_users_autonomy_policy", "users", type_="check")
    op.alter_column(
        "users",
        "autonomy_policy",
        existing_type=sa.String(length=32),
        server_default=sa.text("'write_code'"),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_users_autonomy_policy",
        "users",
        "autonomy_policy in ('cautious', 'write_code', 'less_interrupt', 'managed')",
    )
