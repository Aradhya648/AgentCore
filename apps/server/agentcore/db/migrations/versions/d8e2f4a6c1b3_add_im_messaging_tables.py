"""add IM messaging tables (消息页 = 找人)

Revision ID: d8e2f4a6c1b3
Revises: c9f4a1b7e2d3
Create Date: 2026-06-15 16:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d8e2f4a6c1b3"
down_revision: str | None = "c9f4a1b7e2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IM messaging domain (消息IM.md): human↔human chat + an official
    # account, kept separate from the AI conversation/messages tables. Purely
    # additive — no backfill, existing data untouched.
    op.create_table(
        "chats",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("avatar_url", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("dm_key", sa.String(length=73), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.String(length=500), nullable=True),
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
            "type in ('dm', 'group', 'official')", name="ck_chats_type"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dm_key"),
    )
    op.create_index(op.f("ix_chats_created_by"), "chats", ["created_by"], unique=False)
    op.create_index(
        "ix_chats_last_message_at", "chats", ["last_message_at"], unique=False
    )

    op.create_table(
        "chat_members",
        sa.Column("chat_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "role",
            sa.String(length=20),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.String(length=20),
            server_default=sa.text("'accepted'"),
            nullable=False,
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_read_message_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "muted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role in ('owner', 'admin', 'member')", name="ck_chat_members_role"
        ),
        sa.CheckConstraint(
            "state in ('accepted', 'pending')", name="ck_chat_members_state"
        ),
        sa.PrimaryKeyConstraint("chat_id", "user_id"),
    )
    op.create_index(
        op.f("ix_chat_members_user_id"), "chat_members", ["user_id"], unique=False
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("chat_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("sender_user_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "sender_type",
            sa.String(length=20),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "content_type",
            sa.String(length=20),
            server_default=sa.text("'text'"),
            nullable=False,
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reply_to_message_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("client_msg_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sender_type in ('user', 'official', 'agent')",
            name="ck_chat_messages_sender_type",
        ),
        sa.CheckConstraint(
            "content_type in ('text', 'image', 'file', 'system_card')",
            name="ck_chat_messages_content_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_chat_created",
        "chat_messages",
        ["chat_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_chat_messages_client_msg",
        "chat_messages",
        ["chat_id", "sender_user_id", "client_msg_id"],
        unique=True,
    )

    op.create_table(
        "user_blocks",
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("blocked_user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "blocked_user_id"),
    )

    op.create_table(
        "user_directory_settings",
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "discoverable",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "who_can_dm",
            sa.String(length=20),
            server_default=sa.text("'anyone'"),
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
            "who_can_dm in ('anyone', 'contacts')",
            name="ck_user_directory_who_can_dm",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_directory_settings")
    op.drop_table("user_blocks")
    op.drop_index("uq_chat_messages_client_msg", table_name="chat_messages")
    op.drop_index("ix_chat_messages_chat_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_chat_members_user_id"), table_name="chat_members")
    op.drop_table("chat_members")
    op.drop_index("ix_chats_last_message_at", table_name="chats")
    op.drop_index(op.f("ix_chats_created_by"), table_name="chats")
    op.drop_table("chats")
