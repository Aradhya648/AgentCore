"""Add friendships / friend_requests; who_can_dm contacts→friends; who_can_friend.

Revision ID: e7b4c2a9f1d8
Revises: d5f1a8c2e9b4
Create Date: 2026-08-01 17:00:00.000000

消息IM.md §九: bidirectional friend graph + privacy axes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b4c2a9f1d8"
down_revision: str | None = "d5f1a8c2e9b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "friendships",
        sa.Column("user_a_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_b_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("user_a_id < user_b_id", name="ck_friendships_canonical_order"),
    )
    op.create_index("ix_friendships_user_b_id", "friendships", ["user_b_id"])

    op.create_table(
        "friend_requests",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("from_user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("to_user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("pair_key", sa.String(length=80), nullable=False),
        sa.Column("message", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
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
        sa.CheckConstraint(
            "status in ('pending', 'accepted', 'rejected', 'cancelled')",
            name="ck_friend_requests_status",
        ),
        sa.CheckConstraint(
            "from_user_id <> to_user_id",
            name="ck_friend_requests_not_self",
        ),
    )
    op.create_index(
        "ix_friend_requests_to_status", "friend_requests", ["to_user_id", "status"]
    )
    op.create_index(
        "ix_friend_requests_from_status", "friend_requests", ["from_user_id", "status"]
    )
    op.create_index(
        "uq_friend_requests_pending_pair",
        "friend_requests",
        ["pair_key"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Privacy: contacts → friends; add who_can_friend.
    # Drop the old check first — UPDATE to 'friends' while
    # who_can_dm IN ('anyone','contacts') is still enforced fails.
    op.drop_constraint("ck_user_directory_who_can_dm", "user_directory_settings", type_="check")
    op.execute(
        "UPDATE user_directory_settings SET who_can_dm = 'friends' "
        "WHERE who_can_dm = 'contacts'"
    )
    op.create_check_constraint(
        "ck_user_directory_who_can_dm",
        "user_directory_settings",
        "who_can_dm in ('anyone', 'friends')",
    )
    op.add_column(
        "user_directory_settings",
        sa.Column(
            "who_can_friend",
            sa.String(length=20),
            server_default=sa.text("'anyone'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_user_directory_who_can_friend",
        "user_directory_settings",
        "who_can_friend in ('anyone', 'group_members', 'nobody')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_directory_who_can_friend", "user_directory_settings", type_="check"
    )
    op.drop_column("user_directory_settings", "who_can_friend")
    op.drop_constraint("ck_user_directory_who_can_dm", "user_directory_settings", type_="check")
    op.execute(
        "UPDATE user_directory_settings SET who_can_dm = 'contacts' "
        "WHERE who_can_dm = 'friends'"
    )
    # Recreate old check only after values are back to ('anyone','contacts').
    op.create_check_constraint(
        "ck_user_directory_who_can_dm",
        "user_directory_settings",
        "who_can_dm in ('anyone', 'contacts')",
    )

    op.drop_index("uq_friend_requests_pending_pair", table_name="friend_requests")
    op.drop_index("ix_friend_requests_from_status", table_name="friend_requests")
    op.drop_index("ix_friend_requests_to_status", table_name="friend_requests")
    op.drop_table("friend_requests")
    op.drop_index("ix_friendships_user_b_id", table_name="friendships")
    op.drop_table("friendships")
