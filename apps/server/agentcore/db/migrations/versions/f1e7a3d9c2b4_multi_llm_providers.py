"""BYOK 多服务商列表: user_llm_providers + account pointers + conversation provider

Migrates BYOK from an account-level singleton (``user_llm_keys``, one row per user) to
a list of providers (``user_llm_providers``, many rows per user):

- Create ``user_llm_providers`` (uuid pk, label, key, endpoint, default model, price
  card, supports_tools, status).
- Add account-level default pointers to ``users`` (chat / background, each a
  ``(provider_id, model)`` pair, possibly cross-provider).
- Add ``conversations.model_provider_id`` so an origin=byok override pins its 服务商.
- Data:每行 ``user_llm_keys`` 平移为一条 provider 行 (label 按 base_url 推断厂商名);
  账号 chat 默认指针指向它, 后台指针随 ``background_model`` 迁移; 价卡随迁.
- Drop ``user_llm_keys`` (硬切换, no compat layer).

Revision ID: f1e7a3d9c2b4
Revises: d3b8c1f0a2e6
Create Date: 2026-07-20 18:00:00.000000

"""

import uuid
from collections.abc import Sequence
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1e7a3d9c2b4"
down_revision: str | None = "d3b8c1f0a2e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _providers_table() -> sa.Table:
    return sa.Table(
        "user_llm_providers",
        sa.MetaData(),
        sa.Column("id", postgresql.UUID(as_uuid=False)),
        sa.Column("user_id", postgresql.UUID(as_uuid=False)),
        sa.Column("label", sa.String(100)),
        sa.Column("api_key_enc", sa.LargeBinary()),
        sa.Column("base_url", sa.String(500)),
        sa.Column("default_model", sa.String(200)),
        sa.Column("price_cache_hit", sa.String(40)),
        sa.Column("price_cache_miss", sa.String(40)),
        sa.Column("price_output", sa.String(40)),
        sa.Column("supports_tools", sa.Boolean()),
        sa.Column("status", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def _keys_table() -> sa.Table:
    return sa.Table(
        "user_llm_keys",
        sa.MetaData(),
        sa.Column("user_id", postgresql.UUID(as_uuid=False)),
        sa.Column("api_key_enc", sa.LargeBinary()),
        sa.Column("base_url", sa.String(500)),
        sa.Column("default_model", sa.String(200)),
        sa.Column("price_cache_hit", sa.String(40)),
        sa.Column("price_cache_miss", sa.String(40)),
        sa.Column("price_output", sa.String(40)),
        sa.Column("background_model", sa.String(200)),
        sa.Column("supports_tools", sa.Boolean()),
        sa.Column("status", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def _label_from_base_url(base_url: str | None) -> str:
    """Infer a vendor display name from the endpoint host (迁移期默认 label)."""
    host = (base_url or "").lower()
    for needle, label in (
        ("deepseek", "DeepSeek"),
        ("openai", "OpenAI"),
        ("moonshot", "Moonshot"),
        ("volces", "火山方舟"),
        ("bigmodel", "智谱"),
        ("zhipu", "智谱"),
        ("dashscope", "通义千问"),
        ("anthropic", "Anthropic"),
    ):
        if needle in host:
            return label
    netloc = urlparse(base_url or "").netloc
    return netloc or "BYOK"


def upgrade() -> None:
    op.create_table(
        "user_llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("label", sa.String(length=100), server_default=sa.text("''"), nullable=False),
        sa.Column("api_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "base_url",
            sa.String(length=500),
            server_default=sa.text("'https://api.deepseek.com'"),
            nullable=False,
        ),
        sa.Column(
            "default_model",
            sa.String(length=200),
            server_default=sa.text("'deepseek-v4-flash'"),
            nullable=False,
        ),
        sa.Column("price_cache_hit", sa.String(length=40), nullable=True),
        sa.Column("price_cache_miss", sa.String(length=40), nullable=True),
        sa.Column("price_output", sa.String(length=40), nullable=True),
        sa.Column("supports_tools", sa.Boolean(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'unchecked'"),
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
            "status in ('unchecked', 'active', 'error')",
            name="ck_user_llm_providers_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_llm_providers_user", "user_llm_providers", ["user_id"])

    # Account-level default model pointers (nullable — NULL = no BYOK provider).
    op.add_column(
        "users",
        sa.Column("default_chat_provider_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column("users", sa.Column("default_chat_model", sa.String(length=200), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "default_background_provider_id", postgresql.UUID(as_uuid=False), nullable=True
        ),
    )
    op.add_column(
        "users", sa.Column("default_background_model", sa.String(length=200), nullable=True)
    )

    # Per-conversation BYOK provider for an origin=byok override (NULL = account default).
    op.add_column(
        "conversations",
        sa.Column("model_provider_id", postgresql.UUID(as_uuid=False), nullable=True),
    )

    _migrate_keys_to_providers()

    op.drop_table("user_llm_keys")


def _migrate_keys_to_providers() -> None:
    """Copy each ``user_llm_keys`` row into a provider row + wire the account pointers."""
    conn = op.get_bind()
    keys = _keys_table()
    providers = _providers_table()
    rows = conn.execute(
        sa.select(
            keys.c.user_id,
            keys.c.api_key_enc,
            keys.c.base_url,
            keys.c.default_model,
            keys.c.price_cache_hit,
            keys.c.price_cache_miss,
            keys.c.price_output,
            keys.c.background_model,
            keys.c.supports_tools,
            keys.c.status,
            keys.c.created_at,
            keys.c.updated_at,
        )
    ).mappings().all()

    for row in rows:
        provider_id = str(uuid.uuid4())
        default_model = (row["default_model"] or "deepseek-v4-flash")
        conn.execute(
            providers.insert().values(
                id=provider_id,
                user_id=row["user_id"],
                label=_label_from_base_url(row["base_url"]),
                api_key_enc=row["api_key_enc"],
                base_url=row["base_url"] or "https://api.deepseek.com",
                default_model=default_model,
                price_cache_hit=row["price_cache_hit"],
                price_cache_miss=row["price_cache_miss"],
                price_output=row["price_output"],
                supports_tools=row["supports_tools"],
                status=row["status"] or "unchecked",
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
        background_model = (row["background_model"] or "").strip() or None
        conn.execute(
            sa.text(
                "UPDATE users SET default_chat_provider_id = :pid, "
                "default_chat_model = :chat_model, "
                "default_background_provider_id = :bg_pid, "
                "default_background_model = :bg_model WHERE user_id = :uid"
            ),
            {
                "pid": provider_id,
                "chat_model": default_model,
                "bg_pid": provider_id if background_model else None,
                "bg_model": background_model,
                "uid": row["user_id"],
            },
        )


def downgrade() -> None:
    op.create_table(
        "user_llm_keys",
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("api_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "base_url",
            sa.String(length=500),
            server_default=sa.text("'https://api.deepseek.com'"),
            nullable=False,
        ),
        sa.Column(
            "default_model",
            sa.String(length=200),
            server_default=sa.text("'deepseek-v4-flash'"),
            nullable=False,
        ),
        sa.Column("price_cache_hit", sa.String(length=40), nullable=True),
        sa.Column("price_cache_miss", sa.String(length=40), nullable=True),
        sa.Column("price_output", sa.String(length=40), nullable=True),
        sa.Column("background_model", sa.String(length=200), nullable=True),
        sa.Column("supports_tools", sa.Boolean(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'unchecked'"),
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
            "status in ('unchecked', 'active', 'error')",
            name="ck_user_llm_keys_status",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # Best-effort restore: collapse each account's chat-default provider back to a single
    # key row (multi-provider users lose their extra providers — expected for a downgrade).
    conn = op.get_bind()
    keys = _keys_table()
    providers = _providers_table()
    users_rows = conn.execute(
        sa.text(
            "SELECT user_id, default_chat_provider_id, default_background_model "
            "FROM users WHERE default_chat_provider_id IS NOT NULL"
        )
    ).mappings().all()
    for u in users_rows:
        prov = conn.execute(
            sa.select(
                providers.c.api_key_enc,
                providers.c.base_url,
                providers.c.default_model,
                providers.c.price_cache_hit,
                providers.c.price_cache_miss,
                providers.c.price_output,
                providers.c.supports_tools,
                providers.c.status,
                providers.c.created_at,
                providers.c.updated_at,
            ).where(providers.c.id == u["default_chat_provider_id"])
        ).mappings().first()
        if prov is None:
            continue
        conn.execute(
            keys.insert().values(
                user_id=u["user_id"],
                api_key_enc=prov["api_key_enc"],
                base_url=prov["base_url"],
                default_model=prov["default_model"],
                price_cache_hit=prov["price_cache_hit"],
                price_cache_miss=prov["price_cache_miss"],
                price_output=prov["price_output"],
                background_model=u["default_background_model"],
                supports_tools=prov["supports_tools"],
                status=prov["status"],
                created_at=prov["created_at"],
                updated_at=prov["updated_at"],
            )
        )

    op.drop_column("conversations", "model_provider_id")
    op.drop_column("users", "default_background_model")
    op.drop_column("users", "default_background_provider_id")
    op.drop_column("users", "default_chat_model")
    op.drop_column("users", "default_chat_provider_id")
    op.drop_index("ix_user_llm_providers_user", table_name="user_llm_providers")
    op.drop_table("user_llm_providers")
