"""Admin console schemas: user management, usage/observability dashboards, replay.

The cross-user counterparts of the per-user usage schemas, plus user management
and 会话复盘. All admin-gated (管理员后台.md); reuses the per-user usage schemas.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .usage import (
    CostBreakdown,
    DailyCost,
    ModelCostLine,
    QuotaStatus,
    UsageWindow,
)

# --- Admin (用户管理: 平台管理员后台, admin-only) ---


class AdminUserResponse(BaseModel):
    """A platform account as seen by the admin console (full record + quota state).

    Richer than ``UserResponse`` (the self-view): adds ``status`` and the per-user
    quota overrides so the operator can manage accounts. Each quota override is
    nullable — NULL = inherit the global config threshold for that dimension
    (成本配额与计费.md §一, 决策④); a value (incl. 0 = unlimited) overrides it.
    """

    id: str
    username: str
    display_name: str
    email: str | None
    role: Literal["user", "admin"]
    status: Literal["active", "disabled"]
    is_unlimited: bool
    quota_daily_tokens: int | None
    quota_monthly_cost_usd: float | None
    quota_daily_cost_usd: float | None
    quota_daily_requests: int | None
    created_at: datetime
    # NULL for a live account; a timestamp marks a 注销 (self-service deleted +
    # anonymized) account. The roster hides these by default and renders them as
    # 「已注销」when surfaced — they're tombstones, not manageable accounts.
    deleted_at: datetime | None


class AdminUserListItem(AdminUserResponse):
    """A roster row: the account record + its all-time cumulative spend.

    Extends the account view with ``cost_total`` (all-time, integer nano-USD) so the
    用户管理 roster can both **sort by** and **display** per-user lifetime cost without a
    second round-trip. The client folds the response's ``cny_per_usd`` for ¥.
    """

    cost_total: int


class AdminUserListResponse(BaseModel):
    data: list[AdminUserListItem]
    total: int
    page: int
    page_size: int
    # FX rate to fold each row's nano-USD ``cost_total`` into ¥ (single source: config).
    cny_per_usd: float


class AdminUpdateUserRequest(BaseModel):
    """Partial update of a user's role / status / quota (admin console).

    Tri-state semantics key off which fields are *present* in the request body
    (Pydantic ``model_fields_set``), not their value:
    - field absent        → leave unchanged
    - quota field = null  → clear the override (inherit the global config)
    - quota field = value → set the override (0 = unlimited for that dimension)

    ``is_unlimited`` short-circuits all quota dimensions for trusted accounts.
    Sending ``role``/``status`` that targets the caller's own account in a way that
    would revoke their own admin access is refused at the service layer (no
    self-lockout — the platform always keeps ≥1 active admin).
    """

    role: Literal["user", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None
    is_unlimited: bool | None = None
    quota_daily_tokens: int | None = Field(None, ge=0)
    quota_monthly_cost_usd: float | None = Field(None, ge=0)
    quota_daily_cost_usd: float | None = Field(None, ge=0)
    quota_daily_requests: int | None = Field(None, ge=0)


class AdminResetPasswordResponse(BaseModel):
    """The one-off password minted by an admin reset (重置密码), returned exactly once.

    Plaintext is never persisted — only its hash. The admin hands this to the user,
    whose existing sessions are already revoked, so they must log in with it next.
    """

    temporary_password: str


class AdminSetPasswordRequest(BaseModel):
    """Admin-specified new password (设置密码) for a target account.

    Plaintext is never stored or echoed back — only its hash. Revokes the user's
    sessions on success (same as reset). ``force_change`` defaults true so the user
    must set their own password on next login unless the operator opts out.
    """

    new_password: str = Field(..., min_length=8)
    force_change: bool = True


# --- Admin: 全站用量看板 (P1) + 系统状态 (P2) ---
# The cross-user counterparts of the per-user usage schemas above, plus a
# read-only deployment-status snapshot. Both endpoints are admin-gated
# (管理员后台.md); they reuse UsageWindow / DailyCost / QuotaStatus defined above.


class AdminUserCostLine(BaseModel):
    """One account's spend over a window — the platform 工资单 by user (全站看板).

    Money is integer nano-USD; the client formats ¥ from the summary's single
    ``cny_per_usd`` (no re-pricing).
    """

    user_id: str
    username: str
    display_name: str
    cost_total: int
    # Distinct assistant turns this account ran over the window.
    turns: int


class AdminUsageSummary(BaseModel):
    """Platform-wide usage dashboard (``GET /v1/admin/usage/summary``, admin-only).

    The cross-user counterpart of ``UsageSummary``: today's / this month's totals
    aggregated over *every* account, the Top spenders by user (工资单 by user), and
    the 7-day platform trend. ``billing_mode`` is surfaced so the client frames cost
    honestly — in "byok" these totals are the sum of each user's spend on their
    *own* DeepSeek key (not platform-paid).
    """

    today: UsageWindow
    month: UsageWindow
    # This month's spend split by user (工资单 by user), spend-desc, >0 only, capped.
    month_by_user: list[AdminUserCostLine]
    # This month's spend split by model across *every* account (from ``cost_calls``,
    # never ``cost_events.model``), spend-desc.
    month_by_model: list[ModelCostLine]
    # Last 7 UTC days incl today, oldest-first, zero-filled — the platform trend.
    recent_daily_cost: list[DailyCost]
    cny_per_usd: float
    billing_mode: str


class AdminSystemStatus(BaseModel):
    """Read-only platform status for the admin console (``GET /v1/admin/system``).

    A deployment sanity-check at a glance (管理员后台 P2): the billing mode + global
    quota defaults + FX rate (all deploy-time ``config``, not editable here),
    database reachability, build provenance, and account tallies. Everything is
    read-only — config changes go through env + redeploy, not the console.
    """

    billing_mode: str
    cny_per_usd: float
    # Global quota defaults (config); per-user overrides live on the user record.
    quota: QuotaStatus
    # A live ``SELECT 1`` round-trip succeeded within the probe timeout.
    database_ok: bool
    version: str
    git_sha: str
    built_at: str
    users_total: int
    users_active: int
    admins: int


# --- Admin: 操作审计 (audit trail) ---


class AdminAuditLogLine(BaseModel):
    """One privileged operator action, newest-first in the audit feed."""

    id: str
    actor_id: str
    actor_username: str
    action: str
    target_type: str
    target_id: str | None
    detail: dict[str, Any] | None
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    data: list[AdminAuditLogLine]
    total: int
    page: int
    page_size: int


# --- Admin: 运营观测看板 (观测, P1) ---
# The operator-facing health view, sourced from turn_metrics (the per-turn
# telemetry DB sink) rather than the dev log firehose (logs/dev.jsonl). Admin-gated
# (管理员后台.md). Per-turn money/text are NOT duplicated here — a 会话复盘 (P2)
# joins cost_events + messages by trace_id.


class TurnHealthWindow(BaseModel):
    """Turn health aggregated over a time window (today / 近 7 日) — 全站健康.

    Rates are derived server-side from the raw counts (the client renders them as
    percentages); ``p95_duration_ms`` surfaces the latency tail the average hides.
    """

    turns: int
    errors: int
    # errors / turns in 0..1 (0 when the window has no turns).
    error_rate: float
    avg_duration_ms: int
    p95_duration_ms: int
    avg_rounds: float
    # Turns that delegated to ≥1 member (multi-agent), and its share of turns.
    delegated_turns: int
    delegated_rate: float
    input_tokens: int
    output_tokens: int
    # 协作质量 (学·度量 §2.5): first_plan_survival_rate = share of delegated turns whose opening
    # plan ran without a supervised boundary handing control back (首计划存活率); scope_signals /
    # revises / escalations are raw window sums (漂移 / 返工 / 升级). Default 0 so a window with
    # no delegated turns renders clean.
    first_plan_survival_rate: float = 0.0
    scope_signals: int = 0
    revises: int = 0
    escalations: int = 0


class DailyTurns(BaseModel):
    """One UTC day's turn + error counts — a point in the 观测 trend."""

    # ISO date (YYYY-MM-DD) of the UTC calendar day.
    date: str
    turns: int
    errors: int


class TurnMetricLine(BaseModel):
    """One turn's telemetry row — the 近期错误 feed + 会话复盘 entry point.

    Carries the join keys (``trace_id`` / ``conversation_id``) to drill from a
    failure into the full turn (logs + messages + spend). ``error`` is the
    truncated soft-error text (NULL on success). Built straight from the ORM row.
    """

    turn_id: str
    conversation_id: str
    user_id: str
    agent_id: str | None
    trace_id: str | None
    kind: str
    status: str
    finish_reason: str | None
    error: str | None
    rounds: int
    duration_ms: int
    delegated: bool
    workers: int
    input_tokens: int
    output_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminObservabilitySummary(BaseModel):
    """Platform-wide 运营观测看板 (``GET /v1/admin/observability/summary``, admin-only).

    The operator's health view, sourced from ``turn_metrics`` (not the dev log
    file): today's and the trailing 7-day window health, the 7-day daily trend, and
    the most recent errored turns. Aggregated over *every* account (admin is a
    cross-user surface). Per-turn money/text are NOT here — drill into a turn by
    ``trace_id`` (会话复盘, P2) to join cost_events + messages.
    """

    today: TurnHealthWindow
    week: TurnHealthWindow
    # Last 7 UTC days incl today, oldest-first, zero-filled — the trend bars.
    recent_daily: list[DailyTurns]
    # Most recent errored turns (newest-first, capped) — the 近期错误 feed.
    recent_errors: list[TurnMetricLine]


# --- Admin: 控制台概览 (landing dashboard) ---
# A curated one-call snapshot for the console home, stitched from the same
# aggregates as 用量 / 观测 / 系统 (one extra: distinct active users) so the
# headline numbers never drift from those drill-down pages.


class AdminOverview(BaseModel):
    """Landing dashboard (``GET /v1/admin/overview``, admin-only) — platform pulse.

    Today's vitals (active users / turn health / cost), account tallies, the 7-day
    cost + turn trends, deployment health, and the most recent errors (drillable
    into 会话复盘). Money is integer nano-USD; the client folds ``cny_per_usd`` for ¥.
    """

    # 今日 pulse: distinct users that took a turn, the turn-health rollup (turns /
    # errors / error_rate / p95 / 委派率 / tokens), and total spend today.
    active_users_today: int
    today: TurnHealthWindow
    cost_today: CostBreakdown
    # Account tallies (status-based, same source as 系统状态).
    users_total: int
    users_active: int
    admins: int
    # 7-day trends (oldest-first, zero-filled) — cost bars + turn/error bars.
    recent_daily_cost: list[DailyCost]
    recent_daily_turns: list[DailyTurns]
    # Deployment health + a short recent-errors feed (drill into 会话复盘 by id).
    database_ok: bool
    recent_errors: list[TurnMetricLine]
    cny_per_usd: float
    billing_mode: str


# --- Admin: 用户详情下钻 (用户管理 P0 drill-down) ---
# One account's at-a-glance profile: the full record + its *own* usage (the
# per-user counterpart of the platform 用量看板) + its recent conversations and
# turn activity (each drillable into 会话复盘). Admin cross-user, read-only.


class AdminConversationLine(BaseModel):
    """One of a user's conversations in the 用户详情 roster (compact row).

    id/title/timestamps + message count, newest-activity first. Links to the
    existing 会话复盘 (``GET /v1/admin/observability/conversations/{id}``) for the
    full merged timeline. ``title`` is NULL for an untitled conversation.
    """

    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    # Total messages in the conversation (user + assistant).
    messages: int


class AdminConversationListItem(BaseModel):
    """One row in the platform-wide 对话 roster (``GET /v1/admin/conversations``).

    Cross-user conversation index for ops: owner identity, housekeeping flags,
    message/turn/error rollups, and all-time spend (nano-USD). Soft-deleted
    conversations and tombstone owners are surfaced when requested — the client
    folds ``cny_per_usd`` for ¥. Drill into 会话复盘 by ``id``.
    """

    id: str
    title: str | None
    user_id: str
    username: str | None
    display_name: str | None
    # Set when the owning account was soft-deleted (注销).
    user_deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    archived: bool
    messages: int
    turns: int
    errors: int
    cost_total: int
    # Multi-agent rollup: turns that delegated (≥1 worker) + max workers across those turns.
    # ``delegated_turns > 0`` drives the roster「多 Agent」badge / ``has_delegated`` filter.
    delegated_turns: int = 0
    workers: int = 0


class AdminConversationListResponse(BaseModel):
    """Paginated platform conversation roster (admin-only)."""

    data: list[AdminConversationListItem]
    total: int
    page: int
    page_size: int
    cny_per_usd: float


class AdminTurnListItem(TurnMetricLine):
    """One turn in the platform-wide 回合 feed — TurnMetricLine + list context.

    Carries the owning conversation title and account display identity so an
    operator can triage without opening 复盘 first.
    """

    conversation_title: str | None = None
    username: str | None = None
    display_name: str | None = None
    conversation_deleted_at: datetime | None = None


class AdminTurnListResponse(BaseModel):
    """Paginated platform turn feed (admin-only)."""

    data: list[AdminTurnListItem]
    total: int
    page: int
    page_size: int


class AdminUserDetail(BaseModel):
    """One account's drill-down (``GET /v1/admin/users/{id}/detail``, admin-only).

    Stitches the per-user views an operator needs to understand an account: the
    full record (``user``), the account BYOK default chat/background model names +
    provider count (from the ``users`` pointers / ``user_llm_providers`` — never the
    API key), this account's usage (today/month/
    trend/by-model — the per-user counterpart of ``AdminUsageSummary``),
    its recent conversations, and its recent turn activity (``turn_metrics``, each
    drillable into 会话复盘). Money is integer nano-USD; the client folds the single
    ``cny_per_usd`` for ¥. ``billing_mode`` frames cost honestly (byok = own-key spend).
    """

    user: AdminUserResponse
    # Account BYOK default model pointers (names only; null when unset). 多服务商列表:
    # the chat / background default model, plus how many providers are configured.
    default_model: str | None = None
    background_model: str | None = None
    provider_count: int = 0
    today: UsageWindow
    month: UsageWindow
    # Last 30 days' call-level spend split by model (from ``cost_calls``), spend-desc.
    recent_by_model: list[ModelCostLine]
    # Last 7 UTC days incl today, oldest-first, zero-filled — the trend sparkline.
    recent_daily_cost: list[DailyCost]
    # Recent conversations (newest-activity first, capped).
    conversations: list[AdminConversationLine]
    # Recent turns (newest-first, capped) — each drillable into 会话复盘.
    recent_turns: list[TurnMetricLine]
    cny_per_usd: float
    billing_mode: str


class ReplaySpan(BaseModel):
    """One execution span inside a turn — a tool call or an LLM call — projected
    compactly from ``turn_journal`` for the 复盘 drill-down.

    Deliberately summary-only: NOT the heavy/sensitive replay payload (system
    prompts, full tool results), just what triages a turn — what ran, in which
    round/run, ok?, finish_reason, tokens, and a short preview. Per-span latency is
    omitted: the execution facts don't reliably carry a per-span timestamp yet.
    """

    kind: str  # "tool" | "llm"
    run_id: str | None = None
    round_idx: int | None = None
    # Tool spans:
    name: str | None = None
    success: bool | None = None
    args_preview: str | None = None
    result_preview: str | None = None
    # LLM spans:
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ReplayRun(BaseModel):
    """One agent run in a turn's multi-agent tree (会话复盘 · 协作树节点).

    Lightweight triage projection — NOT the full ``RunsPayload.events``. Sourced
    from ``turn_journal`` via the existing display fold
    (``runs_from_entries`` → ``project_turn``) plus ``message_final`` for full
    worker text. ``spans`` stay on the parent ``ReplayMessage`` and are grouped
    client-side by ``run_id``.
    """

    run_id: str
    agent_id: str
    role: str | None = None
    kind: str = "agent"  # agent | captain | …
    task: str = ""
    status: str = "pending"
    parent_run_id: str | None = None
    depends_on: list[str] = []
    # Worker deliverable body (message_final full text); None when absent.
    content: str | None = None
    # Structured handoff brief {summary/key_points/assumptions/next_steps}, or None.
    debrief: dict | None = None
    output_summary: str | None = None
    error: str | None = None


class ReplayMessage(BaseModel):
    """One message in a 会话复盘 timeline (the thread + per-turn overlays).

    An assistant message carries its turn's telemetry (``metrics``, joined by
    trace_id), spend (``cost_total``, summed from cost_events by message_id), and the
    turn's execution spans (``spans``, projected from turn_journal); user messages
    have none. ``content`` is the raw message text (the prompt / reply) — the
    substance of the post-mortem. Multi-agent turns also carry ``runs`` (lightweight
    tree nodes for triage — not the desktop team canvas).
    """

    id: str
    role: str
    content: str | None
    created_at: datetime
    trace_id: str | None
    metrics: TurnMetricLine | None = None
    # Per-turn spend (integer nano-USD); the client folds ``cny_per_usd`` for ¥.
    cost_total: int = 0
    # The turn's tool/LLM spans (turn_journal projection); empty for user prompts and
    # for turns that journaled nothing (a plain single-agent chat with no tools).
    spans: list[ReplaySpan] = []
    # Multi-agent run tree (empty for plain chat / user prompts).
    runs: list[ReplayRun] = []


class ReplayConversation(BaseModel):
    """The conversation header for a 复盘 (owner identity + title)."""

    id: str
    title: str | None
    user_id: str
    username: str | None
    display_name: str | None
    created_at: datetime


class AdminConversationReplay(BaseModel):
    """One conversation's 复盘 timeline (``GET /v1/admin/observability/conversations/{id}``).

    Merges the three turn sources by trace_id / message_id: the message thread
    (bodies, from ``messages``), per-turn outcome/quality (``turn_metrics``), and
    per-turn spend (``cost_events``). Admin-only, cross-user — the drill-down target
    of the 观测看板's 近期错误 feed (opens a failed turn in full context).
    """

    conversation: ReplayConversation
    messages: list[ReplayMessage]
    # Conversation rollup over its traced turns.
    turns: int
    errors: int
    # Total turn spend (integer nano-USD) + the single FX rate for ¥ display.
    cost_total: int
    cny_per_usd: float
