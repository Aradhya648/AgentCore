"""Conversation domain models: Conversation, Folder, Message, ConversationShare."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid

# --- Conversations ---


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    agent_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        default="00000000-0000-0000-0000-000000000000",
        server_default=text("'00000000-0000-0000-0000-000000000000'"),
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''"))
    # Sidebar housekeeping (对话基础功能补齐):
    # - ``pinned`` floats a conversation to the top of the sidebar / list (ordered
    #   pinned-first, then by recency).
    # - ``archived`` hides a conversation from the default sidebar / grouped list
    #   without deleting it; surfaced only in the「已归档」view, reversible.
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    archived: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    mode: Mapped[str] = mapped_column(String(20), default="chat", server_default=text("'chat'"))
    # Permission axes (会话级权限 · 安全权限与治理):
    # {file_write, command, team_kickoff, host}. Runtime gates read THIS column — not
    # users.autonomy_policy (which only seeds new conversations with a recipe).
    # Default = 少打断: session + auto + skip + ask.
    # Legacy rows / server_default may omit ``host``; ``PermissionAxes.from_mapping`` fills ask.
    permission_axes: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "file_write": "session",
            "command": "auto",
            "team_kickoff": "skip",
            "host": "ask",
        },
        server_default=text(
            "'{\"file_write\":\"session\",\"command\":\"auto\",\"team_kickoff\":\"skip\",\"host\":\"ask\"}'::jsonb"
        ),
    )
    # 深度研究自治（会话级独立旗标）: when True, CEO may auto-adopt worker motion_cards
    # and call debate without a team_preview kickoff (prompt-layer fork + debate-only
    # kickoff waiver). Axes with command=auto ∧ team_kickoff=skip (少打断 / 托管) imply
    # the same via runtime helper — this column is the explicit single-flag path.
    deep_research_auto: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    # Auto-adopted debates started under 深度研究自治 (flag or auto+skip axes). Cap = 1
    # per session; over the limit kickoff + ceo_format gracefully degrade (no error).
    deep_research_auto_debate_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0")
    )
    # Session-level model combination pin (模型组合). NULL = follow account
    # ``users.default_model_profile_id``. Live reference into ``llm_model_profiles``
    # (or a virtual system preset id). Expanded at turn time via
    # ``llm/model_profiles.py`` → main / worker / background slots.
    model_profile_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=False), nullable=True
    )
    # Project this conversation was born into; NULL = 裸聊 (ungrouped). App-level FK
    # (no DB constraint, per repo convention). Soft-deleting a project archives members
    # in place (keeps ``folder_id``); permanent wipe hard-deletes member rows.
    folder_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False), index=True, nullable=True)
    # Desktop's intended local container root for a 裸聊, captured at creation
    # (NULL = cloud intent: web / mobile /「云端临时对话」). Used when resolving
    # effective local binding for ungrouped chats; ignored once ``folder_id`` is set
    # (project chats inherit the project's immutable binding). Auto-promote is vetoed —
    # locality is birth-time / explicit bind only (双模式工作区).
    local_container_root_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 裸聊 scratch workspace binding (per-conversation ``conv:<id>``). The desktop FS
    # root handle for THIS conversation's local scratch. NULL = cloud. Project chats
    # inherit binding from the Folder row instead — this column stays NULL for them.
    local_root_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Sub-path within ``local_root_id`` for the conversation's scratch workspace.
    # "" = the root itself (an explicitly-bound directory). A non-empty segment scopes
    # the workspace under a shared container root.
    local_subpath: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # Long-term memory consolidation watermark (Agent记忆与知识系统 §1.5): the
    # created_at of the last message folded into the user's memory file by the
    # offline consolidation pass. NULL = never consolidated. The runner skips when
    # no message is newer than this, and the sweeper backstop selects conversations
    # whose latest message is newer than it (有未整合的新内容) yet has settled.
    memory_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Long-conversation compaction (执行引擎架构设计 §三 长对话压缩 / conversation/
    # compaction.py). A rolling summary folds turns OLDER than the recency window into
    # 已确立事实 / 决策 / 未决问题 / 文件路径, so a long chat feeds [summary] + recent
    # turns instead of the whole transcript — fighting context rot + cache-lapse cost,
    # not window overflow (DeepSeek's 1M does not overflow). Three columns, all NULL =
    # never compacted (the loader falls back to the plain recent window):
    #   compaction_summary       — the current rolling summary text
    #   compacted_through        — watermark: created_at of the last message folded in
    #   compaction_input_tokens  — the turn input tokens measured at the last (re)compaction
    # Computed OFF the turn by the token-triggered background pass, then REUSED across
    # turns (compute once, never per-turn) so the DeepSeek exact-prefix cache holds —
    # recomputing the prefix every turn would bust it (see runtime/resolve/prompt.py).
    compaction_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_through: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    compaction_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Folders ---
# Project = workspace (项目即工作区). Every folder owns a shared workspace:
# local (``local_root_id`` set) or cloud (both binding columns NULL → disk
# scope ``folder:<id>``). Conversations born into a folder inherit it; bare
# chats keep per-conversation ``conv:<id>`` scratch. Soft-deleted like
# conversations; soft-delete archives member conversations (does not ungroup).


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Local-mode binding: desktop FS root id. NULL + NULL ``local_subpath`` = cloud
    # project (shared ``folder:<id>`` scope). Opaque desktop handle (not a
    # server-owned UUID). Immutable after create (no relocate this period).
    local_root_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Sub-path within ``local_root_id``. NULL/"" = bound at the root itself.
    local_subpath: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Messages ---


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # 全 App 最高频读形「按时序翻页一个对话」: 每个读路径都是
        # WHERE conversation_id = ? ORDER BY created_at [LIMIT ?]
        # (list_latest/list_before/list_after/list_recent/list_recent_after/
        #  list_all_for_conversation/delete_after/latest_created_at)。复合
        # (conversation_id, created_at) 让其走索引有序扫描 + LIMIT 提前停; 并按最左前缀
        # 覆盖「仅按 conversation_id 过滤」(counts_for_conversations / journal load_map 的
        # IN(...)), 故无需再单列索引 conversation_id (项目审计-成本性能专项 PERF-001)。
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # User-referenced attachments metadata (list of {name, path, truncated}).
    attachments: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Web sources consulted for this (assistant) message: list of
    # {url, title, snippet, site}. Rendered as source cards; UI-only metadata.
    citations: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # 回合调研台账（引用即出处 P1, DERIVED）：除 blocked 外全量登记（登记宽）；
    # 成稿闸用 deep_read∪selected。含 id/tier/query/deep_read/selected/doc_kind/
    # registrant/citable。与 citations 池正交；[] = legacy / 无台账。
    evidence_ledger: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # 回合级「下一步推荐」chips (下一步推荐, DERIVED 持久化): the post-turn World B narrow
    # task's 2-4 quick-reply suggestions, minted alongside the title AFTER message_end and
    # written back onto THIS assistant row. Persisted as the twin of Conversation.title
    # (same finalize tail) so reopening a conversation replays the last turn's chips; live
    # they ride the followups_generated event. Empty [] for user rows / turns none minted.
    followups: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # 回合 ¥ 成本 (P2 DERIVED)：finalize 回写的 message_end.cost 快照（nano-USD 分量 +
    # currency；cny_total 在读路径按当前 FX 投影）。与 followups/title 同辙——重载 footer
    # 直接用；hover 工资单明细仍走 GET /v1/messages/{id}/cost（cost_events 台账）。
    # NULL for user / unmetered / pre-feature rows.
    cost: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 回复反馈 (点赞/点踩, 对话基础功能补齐): the user's explicit satisfaction signal on an
    # assistant reply — "up" | "down" | NULL(未评价). Toggleable (re-clicking the same
    # side clears it back to NULL). Stored as a plain durable signal only; it does not
    # feed any runtime logic yet — the column exists so future quality analysis has a
    # first-class place to read from instead of being lost. NULL on user rows.
    feedback: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # The turn's replay payload (team graph / single-agent 思考+工具 timeline) is NO
    # LONGER stored here — it is the唯一事实源 ``turn_journal`` table (§8.3 Turn
    # Journal), keyed by this message id, and PROJECTED into MessageDetail.runs on
    # read. See agentcore.runtime.journal.
    # Correlation key to the turn's runtime logs (logs/dev.jsonl): the assistant
    # message joins to its interaction's full log trace (chat.turn_*/llm/tool/...)
    # — message rows otherwise carry only UUIDs, so trace_id is what makes a turn
    # greppable from a persisted reply. NULL on user / untraced (handoff) messages.
    # 32-hex, minted by core/log_context.new_trace_id (not a DB-format uuid).
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # A1+ 回合文件 diff 基线：云端 labeled 快照 id；本地 sidecar 约定 id=message_id
    #（``.agentcore/baselines/{id}.zip``，可不经本列）。NULL = 未打基线 / 失败 / 旧行
    # → 前端降级工具参数预览。
    baseline_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# --- Conversation shares (公开只读分享链接: 对标 ChatGPT 分享) ---
# A public, read-only link to a snapshot of a conversation. 分享 is an explicit,
# opt-in action (隐私承诺: 分享 = 显式操作、操作前明示), so a row only exists once
# the owner创建分享. The transcript is FROZEN into ``snapshot`` at share time
# (所见即所享): the public page renders that copy, so later edits/deletes to the
# live messages never leak into a shared link, and no future turns are exposed.
# Content-only by design — the snapshot holds just role + content + timestamp, never
# reasoning / cost / team graph / files (those are private). The row id doubles as
# the unguessable URL token (uuid4 = 122 bits). Revoked (not hard-deleted) so a
# killed link 404s immediately while the audit trail survives; cascade-revoked when
# the conversation is deleted or the account is注销 (ownership lifecycle).


class ConversationShare(Base):
    __tablename__ = "conversation_shares"
    __table_args__ = (
        # The owner's "manage shares for this conversation" list.
        Index("ix_conversation_shares_conversation", "conversation_id"),
        # Account-注销 cascade revokes every share a user created.
        Index("ix_conversation_shares_user", "user_id"),
    )

    # PK doubles as the public share token (uuid4, unguessable) — the public URL is
    # ``/shared/<id>``. No separate token column needed (consistent with repo PKs).
    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    # The shared conversation + its owner (app-level FKs, per repo convention).
    conversation_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    # Conversation title captured at share time (the public page heading), frozen
    # alongside the transcript so a later rename doesn't change a live link.
    title: Mapped[str] = mapped_column(String(500), server_default=text("''"))
    # The frozen, content-only transcript: a list of {role, content, created_at(iso)}
    # for the user/assistant turns at share time. Immutable — the public render reads
    # this, never the live messages (所见即所享 + no future-turn leak).
    snapshot: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    # Optional auto-expiry (security default: 30d at create). NULL = never expires.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the owner revokes the link (or a cascade does); a revoked share 404s
    # on the public page. Soft (not a row delete) so revocation is observable and the
    # link can never silently reactivate.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Memory updates (记忆更新对话内可见: Agent记忆与知识系统 §1.6 实时提示) ---
# One offline consolidation pass's applied result, anchored to the conversation that
# triggered it, so the thread can show a「记忆已更新」card at its tail — what the AI
# remembered FROM this conversation (读可见、写也可见). Consolidation runs OFF the turn
# path (memory/consolidation.py), AFTER the turn + its turn_journal are already persisted,
# and is conversation-level (it folds a window of turns), so it is its OWN record — not a
# per-turn ``turn_journal`` fact: a dedicated row keyed by conversation_id (never a message
# id), projected into the messages-window read (latest page only) + pushed live on the
# per-user firehose.


class MemoryUpdateRow(Base):
    """One memory write notice anchored to a conversation (two-layer memory).

    Written when an episodic session summary is stored, a semantic consolidation lands, or
    the CEO ``remember`` tool writes an explicit fact — never silent. ``kind`` selects the
    UI card: ``episodic`` (light tip + ``summary``) vs ``semantic`` (diff ``items``).
    ``items`` is a list of ``{action, file, section, scope, content, target}`` for semantic
    diffs (empty for episodic tips).

    **Lifecycle** (no DB FK — app-level cascade, per repo convention): dropped with its
    conversation on hard-delete (``ConversationRepository.hard_delete``). NOT tied to any
    message id (it post-dates the whole window), so message delete / regenerate never touch
    it — a re-run doesn't un-remember what an earlier pass already learned.
    """

    __tablename__ = "memory_updates"
    __table_args__ = (
        # The conversation-tail card read (newest-first) + whole-conversation cascade.
        Index("ix_memory_updates_conversation", "conversation_id", "created_at"),
        # Account-注销 cascade + future per-user「记忆动态」feed.
        Index("ix_memory_updates_user", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    # "episodic" | "semantic" — card shape for the conversation-tail / feed.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'semantic'"))
    # Episodic: ≤200-char session summary shown in the light tip. Semantic: usually null.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Semantic applied changes: list of {action, file, section, scope, content, target}.
    # Empty for episodic tips. Shape owned by memory/maintenance.py MemoryUpdateItem.
    items: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# --- Message bookmarks (消息收藏: 对话内消息 bookmark → 侧栏「已收藏」) ---
# A user's saved pointer to one message, so an important reply can be found again
# from any device (跨设备 = server-stored, fetched on demand — not a device-local
# star). Per-user and message-level: the (user_id, message_id) pair is unique, so
# re-bookmarking is idempotent and un-bookmarking is a single delete. No DB FK
# (app-level cascade, per repo convention): the row is dropped when its message /
# conversation is hard-deleted (regenerate / single-message delete / conversation
# purge), and the「已收藏」list INNER JOINs live messages+conversations so a
# not-yet-cascaded or soft-deleted-conversation row never renders anyway.


class MessageBookmark(Base):
    __tablename__ = "message_bookmarks"
    __table_args__ = (
        # One bookmark per user per message; re-adding the same pair is a no-op.
        UniqueConstraint(
            "user_id", "message_id", name="uq_message_bookmarks_user_message"
        ),
        # The「已收藏」list read: a user's bookmarks, newest-first.
        Index("ix_message_bookmarks_user_created", "user_id", "created_at"),
        # Per-conversation star-state read + conversation-purge cascade.
        Index("ix_message_bookmarks_conversation", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    # The bookmarking user (app-level FK → users; account注销 cascades these rows).
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    # The owning conversation (denormalized so a jump / star-state / purge cascade
    # needs no message round-trip).
    conversation_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    # The bookmarked message.
    message_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# --- External directory grants (W3 区外授权: 对话级持久, 非进程生命周期) ---
# Server holds alias / root_id / label / mode only. Absolute OS paths stay on the
# desktop (``fs-session-grants.json``). Orthogonal to workspace binding. Cleared on
# revoke / conversation soft-delete / hard-delete cascade.


class ConversationExternalGrant(Base):
    """One conversation-scoped external directory grant under ``external/<alias>/``.

    **Lifecycle** (no DB FK — app-level, per repo convention): created/updated via
    ``POST …/external-grants``; dropped on revoke, soft-delete clear, or
    ``ConversationRepository.hard_delete`` cascade. Desktop reconciles root_id ↔
    local path on open; orphans without a desktop path are revoked server-side.
    """

    __tablename__ = "conversation_external_grants"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "alias",
            name="uq_conversation_external_grants_conv_alias",
        ),
        UniqueConstraint(
            "conversation_id",
            "root_id",
            name="uq_conversation_external_grants_conv_root",
        ),
        Index("ix_conversation_external_grants_conversation", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    # Desktop authorized-root handle (never an absolute path).
    root_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''"))
    # "readonly" | "organize"
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'readonly'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
