"""User identity and social settings: User, UserBlock, UserDirectorySettings."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid

# --- Users ---
# Primary key is user_id (the users table's established convention); other
# tables reference it via a `user_id` foreign-key column (app-level integrity).


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('user', 'admin')", name="ck_users_role"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_users_status"),
        CheckConstraint(
            "autonomy_policy in ('cautious', 'less_interrupt', 'managed')",
            name="ck_users_autonomy_policy",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    # Login identifier (D1: username + password). Unique, required.
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), server_default=text("''"))
    # Optional, reserved for future password recovery / OAuth.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    # Object-storage key of the user's avatar (头像), e.g.
    # ``avatars/<user_id>/<hash>.webp``; NULL = no avatar (UI shows the initial).
    # Stores the storage key, not a URL — the served URL is derived at the API edge
    # (UserResponse.avatar_url) so the backend stays agnostic of its public origin.
    # The bytes live in object storage (storage/assets.py), never in the row.
    avatar_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user", server_default=text("'user'"))
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'")
    )
    # --- Per-user quota overrides (成本配额与计费.md §一, 决策④) ---
    # `is_unlimited` short-circuits all three quota checks (operator/trusted
    # accounts). The three override columns are NULL = inherit the global config
    # threshold for that dimension; a non-null value (including 0 = unlimited)
    # overrides it. Monthly cost mirrors the config unit (float USD), converted to
    # nano-USD at check time. Resolved by `QuotaLimits.for_user`.
    is_unlimited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    quota_daily_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quota_monthly_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 日成本 backstop override (成本配额与计费 §〇·六 F2). NULL = inherit config; 0 =
    # unlimited for this user. USD like quota_monthly_cost_usd (→ nano at check time).
    quota_daily_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    quota_daily_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Legacy column: product memory gate is always on (定案 A). Retained so we avoid
    # a destructive migration; resolve + user API ignore this value. Defaults True.
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    # Legacy column: conversation-log access is product-always-on (定案 A). Retained
    # without a drop migration; resolve + user API ignore this value. Defaults True.
    conversation_history_access: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    # Default permission recipe for new conversations (安全权限与治理 · AutonomyPolicy).
    # cautious | less_interrupt (default) | managed — seeds conversation.permission_axes;
    # plan_review / checkpoint confirmation unchanged.
    autonomy_policy: Mapped[str] = mapped_column(
        String(32), default="less_interrupt", server_default=text("'less_interrupt'")
    )
    # --- 账号默认模型组合 (模型组合配置 · llm_model_profiles) ---
    # 指向用户组合或系统预置虚拟 id（5.2 / Grok 4.5）。NULL = 解析时回落系统「5.2」预置。
    # 活引用：改组合定义 → 下一 turn 用新展开。与场景 ProfileParams（温度等）无关。
    default_model_profile_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
    # Self-service account deletion (注销账户). NULL = live account; a timestamp marks
    # a user-initiated deletion. On delete the row is soft-deleted + anonymized
    # (username → "deleted_<id>", email → NULL) so the unique identifiers free up for
    # re-registration, while the append-only cost ledger (不变量①) stays intact.
    # Distinct from `status='disabled'` (admin-disabled, recoverable): a deleted
    # account is terminal. `get_current_user` already refuses non-active users, so a
    # deletion also sets status='disabled' to kill live tokens on the next request.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserBlock(Base):
    __tablename__ = "user_blocks"

    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    blocked_user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UserDirectorySettings(Base):
    __tablename__ = "user_directory_settings"
    __table_args__ = (
        CheckConstraint(
            "who_can_dm in ('anyone', 'contacts')",
            name="ck_user_directory_who_can_dm",
        ),
    )

    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    # Open search is the product default (任意搜人); users may opt out per-axis.
    discoverable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    who_can_dm: Mapped[str] = mapped_column(
        String(20), default="anyone", server_default=text("'anyone'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
