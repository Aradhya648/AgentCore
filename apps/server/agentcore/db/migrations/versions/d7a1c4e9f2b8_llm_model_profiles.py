"""模型组合硬切: llm_model_profiles + drop 三指针 / 会话 model*

Revision ID: d7a1c4e9f2b8
Revises: c4e8f2a1b9d3
Create Date: 2026-07-25

迁移账号三指针 →「当前配置」组合并设 default；会话主模型覆盖 → 隐式组合挂会话；
再 drop users 六列与 conversations.model / model_origin / model_provider_id。
系统预置为虚拟 id，不入库（历史三档已收口为固定平台组合，见 llm/model_profiles）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7a1c4e9f2b8"
down_revision: str | None = "c4e8f2a1b9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Virtual system preset ids (must match agentcore.llm.model_profiles).
_SYSTEM_BALANCED = "00000000-0000-4000-8000-000000000002"


def upgrade() -> None:
    op.create_table(
        "llm_model_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default=sa.text("'user'")
        ),
        sa.Column("main_origin", sa.String(length=20), nullable=False),
        sa.Column(
            "main_provider_id", postgresql.UUID(as_uuid=False), nullable=True
        ),
        sa.Column("main_model", sa.String(length=200), nullable=False),
        sa.Column("worker_origin", sa.String(length=20), nullable=True),
        sa.Column(
            "worker_provider_id", postgresql.UUID(as_uuid=False), nullable=True
        ),
        sa.Column("worker_model", sa.String(length=200), nullable=True),
        sa.Column("background_origin", sa.String(length=20), nullable=True),
        sa.Column(
            "background_provider_id", postgresql.UUID(as_uuid=False), nullable=True
        ),
        sa.Column("background_model", sa.String(length=200), nullable=True),
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
            "kind in ('user', 'implicit')", name="ck_llm_model_profiles_kind"
        ),
        sa.CheckConstraint(
            "main_origin in ('platform', 'byok')",
            name="ck_llm_model_profiles_main_origin",
        ),
        sa.CheckConstraint(
            "worker_origin is null or worker_origin in ('platform', 'byok')",
            name="ck_llm_model_profiles_worker_origin",
        ),
        sa.CheckConstraint(
            "background_origin is null or background_origin in ('platform', 'byok')",
            name="ck_llm_model_profiles_background_origin",
        ),
    )
    op.create_index(
        "ix_llm_model_profiles_user", "llm_model_profiles", ["user_id"]
    )

    op.add_column(
        "users",
        sa.Column(
            "default_model_profile_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "model_profile_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )

    conn = op.get_bind()

    # --- Backfill: account three-pointers → 「当前配置」 profile + default -----------
    users = conn.execute(
        sa.text(
            """
            SELECT user_id,
                   default_chat_provider_id, default_chat_model,
                   default_background_provider_id, default_background_model,
                   default_worker_provider_id, default_worker_model
            FROM users
            WHERE deleted_at IS NULL
            """
        )
    ).mappings().all()

    for u in users:
        chat_pid = u["default_chat_provider_id"]
        chat_model = (u["default_chat_model"] or "").strip() or None
        bg_pid = u["default_background_provider_id"]
        bg_model = (u["default_background_model"] or "").strip() or None
        worker_pid = u["default_worker_provider_id"]
        worker_model = (u["default_worker_model"] or "").strip() or None

        has_pointer = any(
            [chat_pid, chat_model, bg_pid, bg_model, worker_pid, worker_model]
        )
        if not has_pointer:
            first = conn.execute(
                sa.text(
                    "SELECT id, default_model FROM user_llm_providers "
                    "WHERE user_id = :uid ORDER BY created_at ASC LIMIT 1"
                ),
                {"uid": u["user_id"]},
            ).first()
            if first is None:
                # No BYOK either → default to then-current system balanced virtual id.
                conn.execute(
                    sa.text(
                        "UPDATE users SET default_model_profile_id = :pid WHERE user_id = :uid"
                    ),
                    {"pid": _SYSTEM_BALANCED, "uid": u["user_id"]},
                )
                continue
            # Had providers but no pointers → seed 「当前配置」 from first provider.
            chat_pid = first[0]
            chat_model = (first[1] or "").strip() or "deepseek-v4-flash"
            has_pointer = True

        if chat_pid:
            main_origin = "byok"
            main_provider_id = chat_pid
            if not chat_model:
                row = conn.execute(
                    sa.text(
                        "SELECT default_model FROM user_llm_providers "
                        "WHERE id = :id AND user_id = :uid"
                    ),
                    {"id": chat_pid, "uid": u["user_id"]},
                ).first()
                chat_model = (row[0] if row else None) or "deepseek-v4-flash"
            main_model = chat_model
        elif chat_model:
            main_origin = "platform"
            main_provider_id = None
            main_model = chat_model
        else:
            # Background/worker set but no chat — invent main from first provider or flash.
            first = conn.execute(
                sa.text(
                    "SELECT id, default_model FROM user_llm_providers "
                    "WHERE user_id = :uid ORDER BY created_at ASC LIMIT 1"
                ),
                {"uid": u["user_id"]},
            ).first()
            if first:
                main_origin = "byok"
                main_provider_id = first[0]
                main_model = (first[1] or "").strip() or "deepseek-v4-flash"
            else:
                main_origin = "platform"
                main_provider_id = None
                main_model = "deepseek-v4-flash"

        worker_origin = None
        worker_provider_id = None
        worker_model_v = None
        if worker_pid or worker_model:
            if worker_pid:
                worker_origin = "byok"
                worker_provider_id = worker_pid
                if not worker_model:
                    row = conn.execute(
                        sa.text(
                            "SELECT default_model FROM user_llm_providers "
                            "WHERE id = :id AND user_id = :uid"
                        ),
                        {"id": worker_pid, "uid": u["user_id"]},
                    ).first()
                    worker_model = (row[0] if row else None) or "deepseek-v4-flash"
                worker_model_v = worker_model
            else:
                worker_origin = "platform"
                worker_model_v = worker_model

        bg_origin = None
        bg_provider_id = None
        bg_model_v = None
        if bg_pid or bg_model:
            if bg_pid:
                bg_origin = "byok"
                bg_provider_id = bg_pid
                if not bg_model:
                    row = conn.execute(
                        sa.text(
                            "SELECT default_model FROM user_llm_providers "
                            "WHERE id = :id AND user_id = :uid"
                        ),
                        {"id": bg_pid, "uid": u["user_id"]},
                    ).first()
                    bg_model = (row[0] if row else None) or "deepseek-v4-flash"
                bg_model_v = bg_model
            else:
                bg_origin = "platform"
                bg_model_v = bg_model

        profile_id = conn.execute(sa.text("SELECT gen_random_uuid()::text")).scalar()
        conn.execute(
            sa.text(
                """
                INSERT INTO llm_model_profiles (
                    id, user_id, name, kind,
                    main_origin, main_provider_id, main_model,
                    worker_origin, worker_provider_id, worker_model,
                    background_origin, background_provider_id, background_model
                ) VALUES (
                    :id, :uid, :name, 'user',
                    :mo, :mp, :mm,
                    :wo, :wp, :wm,
                    :bo, :bp, :bm
                )
                """
            ),
            {
                "id": profile_id,
                "uid": u["user_id"],
                "name": "当前配置",
                "mo": main_origin,
                "mp": main_provider_id,
                "mm": main_model,
                "wo": worker_origin,
                "wp": worker_provider_id,
                "wm": worker_model_v,
                "bo": bg_origin,
                "bp": bg_provider_id,
                "bm": bg_model_v,
            },
        )
        conn.execute(
            sa.text(
                "UPDATE users SET default_model_profile_id = :pid WHERE user_id = :uid"
            ),
            {"pid": profile_id, "uid": u["user_id"]},
        )

    # --- Backfill: conversation model override → implicit profile --------------------
    convs = conn.execute(
        sa.text(
            """
            SELECT id, user_id, model, model_origin, model_provider_id
            FROM conversations
            WHERE deleted_at IS NULL
              AND model IS NOT NULL
              AND btrim(model) <> ''
            """
        )
    ).mappings().all()

    for c in convs:
        model = (c["model"] or "").strip()
        origin_raw = c["model_origin"]
        provider_id = c["model_provider_id"]
        if origin_raw in ("byok", "platform"):
            origin = origin_raw
        else:
            # Legacy: has provider → byok, else platform.
            origin = "byok" if provider_id else "platform"
        if origin == "platform":
            provider_id = None
        profile_id = conn.execute(sa.text("SELECT gen_random_uuid()::text")).scalar()
        conn.execute(
            sa.text(
                """
                INSERT INTO llm_model_profiles (
                    id, user_id, name, kind,
                    main_origin, main_provider_id, main_model,
                    worker_origin, worker_provider_id, worker_model,
                    background_origin, background_provider_id, background_model
                ) VALUES (
                    :id, :uid, :name, 'implicit',
                    :mo, :mp, :mm,
                    NULL, NULL, NULL,
                    NULL, NULL, NULL
                )
                """
            ),
            {
                "id": profile_id,
                "uid": c["user_id"],
                "name": f"会话覆盖 · {model}",
                "mo": origin,
                "mp": provider_id,
                "mm": model,
            },
        )
        conn.execute(
            sa.text(
                "UPDATE conversations SET model_profile_id = :pid WHERE id = :cid"
            ),
            {"pid": profile_id, "cid": c["id"]},
        )

    # --- Drop legacy columns --------------------------------------------------------
    op.drop_constraint("ck_conversations_model_origin", "conversations", type_="check")
    op.drop_column("conversations", "model_provider_id")
    op.drop_column("conversations", "model_origin")
    op.drop_column("conversations", "model")

    op.drop_column("users", "default_worker_model")
    op.drop_column("users", "default_worker_provider_id")
    op.drop_column("users", "default_background_model")
    op.drop_column("users", "default_background_provider_id")
    op.drop_column("users", "default_chat_model")
    op.drop_column("users", "default_chat_provider_id")


def downgrade() -> None:
    # Hard-cut feature: restore empty legacy columns only (no reverse data migration).
    op.add_column(
        "users",
        sa.Column(
            "default_chat_provider_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("default_chat_model", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "default_background_provider_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("default_background_model", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "default_worker_provider_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("default_worker_model", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("model", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("model_origin", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "model_provider_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_conversations_model_origin",
        "conversations",
        "model_origin is null or model_origin in ('platform', 'byok')",
    )
    op.drop_column("conversations", "model_profile_id")
    op.drop_column("users", "default_model_profile_id")
    op.drop_index("ix_llm_model_profiles_user", table_name="llm_model_profiles")
    op.drop_table("llm_model_profiles")
