"""Replace permission_preset with three-axis permission_axes; recipe AutonomyPolicy.

Revision ID: a4f7c2e9b1d8
Revises: c8f3a1e9b2d4
Create Date: 2026-07-27 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4f7c2e9b1d8"
down_revision: str | None = "c8f3a1e9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_AXES = '{"file_write":"session","command":"kickoff","team_kickoff":"rules"}'


def upgrade() -> None:
    # conversations: drop old enum column; add JSONB three-axis (dev: no row migration).
    op.drop_constraint("ck_conversations_permission_preset", "conversations", type_="check")
    op.drop_column("conversations", "permission_preset")
    op.add_column(
        "conversations",
        sa.Column(
            "permission_axes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_AXES}'::jsonb"),
        ),
    )

    # users.autonomy_policy: old three values → recipe ids (dev: wipe to write_code).
    op.drop_constraint("ck_users_autonomy_policy", "users", type_="check")
    op.execute("UPDATE users SET autonomy_policy = 'write_code'")
    op.alter_column(
        "users",
        "autonomy_policy",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
        server_default=sa.text("'write_code'"),
    )
    op.create_check_constraint(
        "ck_users_autonomy_policy",
        "users",
        "autonomy_policy in ('cautious', 'write_code', 'less_interrupt', 'managed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_autonomy_policy", "users", type_="check")
    op.execute("UPDATE users SET autonomy_policy = 'first_grant'")
    op.alter_column(
        "users",
        "autonomy_policy",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
        server_default=sa.text("'first_grant'"),
    )
    op.create_check_constraint(
        "ck_users_autonomy_policy",
        "users",
        "autonomy_policy in ('always_ask', 'first_grant', 'full_auto')",
    )

    op.drop_column("conversations", "permission_axes")
    op.add_column(
        "conversations",
        sa.Column(
            "permission_preset",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'workspace'"),
        ),
    )
    op.create_check_constraint(
        "ck_conversations_permission_preset",
        "conversations",
        "permission_preset in ('observe', 'workspace', 'full_trust')",
    )
