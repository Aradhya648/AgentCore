"""Message, attachment, interaction-resolve, and turn schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from agentcore.api.schemas.usage import CostBreakdown, UsageBreakdown
from agentcore.runtime.approvals import ApprovalDecision, DelegationAuthorizationDecision
from agentcore.runtime.checkpoints import AskCheckpointIntent, CheckpointDecision
from agentcore.runtime.suspension import SuspensionKind


class MessageAttachment(BaseModel):
    """A piece of context the user referenced (@-mention or paperclip).

    Text files carry client-extracted ``text`` (images stay out of scope until a
    vision model). Binary files are **resident-first** (引用即驻留): the desktop
    copies raw bytes into the conversation workspace ``attachments/`` and sends
    ``workspace_path`` + ``binary=True`` with empty ``text``. Server-side分流预解析
    then extracts text for docx/pdf/pptx/txt 等 (markitdown → ``*.md`` copy); xlsx/csv
    stay path-only so workers can ``code_execute``. ``kind="conversation"`` references
    another of the user's conversations: recent messages are materialized into
    ``text`` client-side, and ``conversation_id`` records which one (for the chip +
    later jump).
    """

    name: str = Field(..., min_length=1, max_length=500)
    path: str = Field(..., max_length=4000)
    # File: extracted text (empty when ``binary`` and not yet pre-parsed). Directory:
    # recursive listing. Conversation: recent messages. Optional so binary residents
    # need not invent a placeholder body (backward compatible).
    text: str = Field(default="", max_length=300_000)
    truncated: bool = False
    kind: Literal["file", "dir", "conversation"] = "file"
    # Set only for kind="conversation": the referenced conversation's id.
    conversation_id: str | None = None
    # True when the attachment is a non-UTF-8 blob already (or about to be) resident
    # under ``workspace_path``. Text-like binaries may still gain server-side
    # ``text`` after分流预解析; spreadsheets remain path-only for ``code_execute``.
    binary: bool = False
    # Client-pre-resident path under ``attachments/`` (引用即驻留). When set,
    # ``persist_attachments`` skips rewriting and keeps this path.
    workspace_path: str | None = None


class StoredAttachment(BaseModel):
    """Persisted attachment display metadata (no extracted text).

    ``workspace_path`` is set when the attachment was written into the durable
    project space (附件驻留 / 引用即驻留): a workspace-relative path under
    ``attachments/`` that the file-download API can serve. ``None`` for directory /
    conversation chips (nothing is written as a workspace file).
    """

    name: str
    path: str
    truncated: bool = False
    kind: Literal["file", "dir", "conversation"] = "file"
    workspace_path: str | None = None
    # Set only for kind="conversation": the referenced conversation's id, so the
    # stored chip can label it and (later) jump back to that conversation.
    conversation_id: str | None = None
    # Byte size of the stored file, surfaced for IM file chips (Stage 4 富消息).
    # None for directory / conversation chips (no single stored blob).
    size_bytes: int | None = None
    # Workspace-relative path to a generated WebP thumbnail for an image
    # attachment (Stage 4 富消息); the bubble inlines this instead of the full
    # original. None when no thumbnail was generated.
    thumb_path: str | None = None
    # True when the resident file is a binary blob. Text-like binaries may still
    # have been pre-parsed into a sibling ``*.md`` in the workspace (not stored here).
    binary: bool = False


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=32000)
    # 同对话再发分流（运行时三模型 · Steer/Queue）：必填；缺 → 422；开发期无缺省兼容层。
    delivery: Literal["steer", "queue"]
    attachments: list[MessageAttachment] = Field(default_factory=list, max_length=20)
    # Soft gate: set when this turn is expected to call orchestration tools (delegate/debate).
    # Triggers a preflight warning (not a block) when probe recorded supports_tools=false.
    # Locality is conversation/project state (birth-time bind), not a per-turn field —
    # auto-promote is vetoed (双模式工作区).
    requires_tools: bool = False


class RegenerateMessageRequest(BaseModel):
    """Re-run a turn from an existing user message.

    The path's ``message_id`` must be a user message. When ``content`` is set the
    user message is edited in place first (edit-and-resend); otherwise the stored
    text is reused as-is (plain regenerate). Either way, every message after that
    user turn is dropped and the assistant reply is produced anew.
    """

    content: str | None = Field(None, min_length=1, max_length=32000)


class SetMessageFeedbackRequest(BaseModel):
    """Set or clear the user's 点赞/点踩 on an assistant message (回复反馈).

    ``feedback`` is ``"up"`` / ``"down"`` to rate the reply, or ``null`` to clear the
    rating back to 未评价 (toggling the same side off). The route does not restrict by
    role — rating is only meaningful on assistant replies, but a value on any row is a
    harmless store.
    """

    feedback: Literal["up", "down"] | None = None


# --- Interaction resolve (§8.2 unified suspend-resume bridge) ---
# One ``POST /conversations/{id}/interactions/{interaction_id}`` settles hot-path
# interactions; the body is discriminated on ``kind`` (approval /
# delegation_authorization / client_tool / escalation / stage_card). Cold-path
# ``ask_user`` / ``plan_review`` / ``team_preview`` are NOT in this union — they
# finalize the turn and continue via ``POST .../resume``.


class ResolveApprovalInteraction(BaseModel):
    """Settle a paused GRANTABLE tool call (``approval`` interaction).

    ``decision`` is one of ``approve`` (allow this one call), ``approve_always``
    (allow this tool for the rest of the turn), or ``deny`` (refuse).
    """

    kind: Literal["approval"] = "approval"
    decision: ApprovalDecision


class WorkspaceOpError(BaseModel):
    """A typed failure from a desktop-run local-workspace op (双模式工作区 P2).

    ``kind`` names the ``WorkspaceError`` subclass to re-raise on the server (e.g.
    ``PathNotFound``, ``OutsideWorkspace``) so the file tool maps it to the same
    message as cloud mode; ``count`` carries the match count for ``AmbiguousMatch``
    (str_replace). An unknown ``kind`` degrades to a generic I/O error.
    """

    kind: str = Field(..., max_length=64)
    detail: str = Field("", max_length=2000)
    count: int | None = None


class ResolveDelegationAuthorizationInteraction(BaseModel):
    """Settle a paused per-delegation authorization (``delegation_authorization``).

    Raised before workers start so the user can grant medium-risk tools for the
    whole delegation in one click. ``grant_delegation`` whitelists code_execute +
    file-mutation tools for this delegation; ``per_call`` keeps per-call approval;
    ``deny`` refuses to start workers.
    """

    kind: Literal["delegation_authorization"] = "delegation_authorization"
    decision: DelegationAuthorizationDecision


class ResolveClientToolInteraction(BaseModel):
    """Deliver a bound desktop's result for a paused local-workspace op (``client_tool``).

    ``ok`` true → ``value`` is the op's result (op-specific: file text, a directory
    listing, a grep result, …; bytes are base64). ``ok`` false → ``error`` describes
    the typed failure to re-raise. The pending op (awaiting in the live SSE turn)
    resumes with this envelope.
    """

    kind: Literal["client_tool"] = "client_tool"
    ok: bool
    value: Any | None = None
    error: WorkspaceOpError | None = None


class ResolveEscalationInteraction(BaseModel):
    """Settle a worker's blocking escalate (``escalation`` interaction, 阻塞式求决策 §4.5).

    Raised when a delegated worker hit a「只有用户能定、且猜错就作废」fork and suspended
    itself. Classic (non-coordination) path asks the user; coordination path awaits CEO
    ``resolve_escalation`` (Invariant B: solo never uses that tool). The user either answers
    (``answer``) or chooses 按假设继续 (``use_assumption`` true → wire status ``assumed``).
    Write-lock conflicts may set ``transfer_ownership`` to path-handoff to the escalator.
    A wall-clock miss is ``timed_out``. A late resolve falls through as 404.
    """

    kind: Literal["escalation"] = "escalation"
    answer: str = Field("", max_length=4000)
    use_assumption: bool = False
    transfer_ownership: bool = False


class ResolveStageCardInteraction(BaseModel):
    """Settle a stage progression card（批 B · 阶段推进卡）.

    ``start_debate``：机制直起辩论（可带 ``motion_override`` / ``note`` 嘱咐）。
    ``research_first``：留痕并回灌 CEO 追加调研。改写 motion 检定失败 → 422，卡保持 pending。
    """

    kind: Literal["stage_card"] = "stage_card"
    decision: Literal["start_debate", "research_first"]
    note: str = Field("", max_length=4000)
    motion_override: str | None = Field(None, max_length=2000)


# Discriminated union body for the unified resolve endpoint.
ResolveInteractionRequest = (
    ResolveApprovalInteraction
    | ResolveDelegationAuthorizationInteraction
    | ResolveClientToolInteraction
    | ResolveEscalationInteraction
    | ResolveStageCardInteraction
)


def interaction_result_from_body(body: ResolveInteractionRequest) -> Any:
    """Project a resolve-interaction body into the engine-side result its awaiter expects.

    The unified bridge (``runtime/interaction.py``) settles each suspend kind with a
    different typed result, so the wire body is coerced per kind BEFORE it reaches
    ``InteractionRegistry.resolve``:

    - ``approval`` → the bare :class:`~agentcore.runtime.approvals.ApprovalDecision`
      (the gate compares it by identity, so it MUST be the enum member, never a plain
      string — a bare ``"approve_always"`` would silently fail the grant/sweep checks);
    - ``client_tool`` → the desktop op's result envelope dict.

    Shared by the cloud resolve route (``routes/conversations.py``) and the sidecar's
    ``respond`` (``sidecar/server.py``) so both transports settle an interaction
    identically — one construction point, no drift between cloud and local.
    """
    if isinstance(body, ResolveApprovalInteraction):
        return body.decision
    if isinstance(body, ResolveDelegationAuthorizationInteraction):
        return body.decision
    if isinstance(body, ResolveClientToolInteraction):
        return {
            "ok": body.ok,
            "value": body.value,
            "error": body.error.model_dump() if body.error else None,
        }
    if isinstance(body, ResolveEscalationInteraction):
        # 阻塞式求决策: the escalate channel awaits {answer} | {use_assumption};
        # transfer_ownership 为写权冲突结构化裁决。
        return {
            "answer": body.answer,
            "use_assumption": body.use_assumption,
            "transfer_ownership": body.transfer_ownership,
        }
    if isinstance(body, ResolveStageCardInteraction):
        return {
            "decision": body.decision,
            "note": body.note,
            "motion_override": body.motion_override,
        }

    raise ValueError(f"unknown interaction kind: {getattr(body, 'kind', None)!r}")


class SubmitRunRedirectRequest(BaseModel):
    """User mid-flight steer for one running worker (中间可见性 Phase 2a).

    Queued while ``delegate`` drives; the scheduler drains and applies cancel + re-run
    in a later step. Does not pause the turn (parallel siblings keep running).
    """

    execution_id: str = Field(..., min_length=1, max_length=128)
    run_id: str = Field(..., min_length=1, max_length=128)
    feedback: str = Field(..., min_length=1, max_length=4000)


class SubmitRunRedirectResponse(BaseModel):
    ok: bool = True
    queued: int = Field(..., description="Pending redirect count for this execution after enqueue.")


class SubmitDebateSteerRequest(BaseModel):
    """Ambient debate steer — fire-and-forget boss intervention (辩论编排设计.md §六).

    Queued while ``debate`` drives; the Moderator drains at the next round boundary
    (non-blocking). ``decision=continue`` (+ optional ``focus``/``ask``) folds into the
    existing pending_interjections / focus_override path; ``conclude`` stops at that
    boundary (current round finishes first — never mid-generation).
    """

    execution_id: str = Field(..., min_length=1, max_length=128)
    decision: Literal["continue", "conclude"] = "continue"
    focus: str = Field("", max_length=2000)
    ask: str = Field("", max_length=2000)
    ask_target: str = Field("", max_length=200)


class SubmitDebateSteerResponse(BaseModel):
    ok: bool = True
    queued: int = Field(..., description="Pending steer count for this execution after enqueue.")


class AcceptRunOutcomeRequest(BaseModel):
    """User explicitly accepts a run's terminal outcome that could not be auto-recovered
    (跑一半改方向 Step 4 · 忽略路径收口).

    Triggers surfaced from the audit trail / status strip: a ``deterministic_failure``
    (non-retryable upstream failure — 重试徒劳), a ``redirect_ignored`` (「立即改此人」steer
    that arrived too late), or ``recovery_ignored`` (status-strip「忽略」救火 abandon).
    Recording the acceptance (后端记录) replaces the old frontend-only ``clearExecution`` so
    the delegated-turn audit trail carries「用户主动接受此结果」. Idempotent per (turn, run).
    """

    run_id: str = Field(..., min_length=1, max_length=128)
    reason: Literal[
        "deterministic_failure",
        "redirect_ignored",
        "recovery_ignored",
    ]
    execution_id: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=1000)


class AcceptRunOutcomeResponse(BaseModel):
    ok: bool = True
    recorded: bool = Field(
        ...,
        description="True if newly recorded; False if already accepted (idempotent no-op).",
    )
    action: str = "run.outcome_accepted"


class ResumeTurnRequest(BaseModel):
    """Body for ``POST .../messages/{message_id}/resume`` (结构化挂起 2b).

    Continues a turn that paused at a plan_review / ask_user checkpoint and was
    DURABLY persisted (so it survived a client disconnect / server restart — the live
    in-process resolve is the corresponding interaction instead). Same decision
    vocabulary as the live resolve: ``continue`` (proceed — run the gated downstream
    for plan_review / accept the CEO direction for ask_user), ``adjust`` (inject
    ``note`` as a steer, then continue), or ``stop`` (end the turn here). ``selected``
    carries the option(s) the user picked from an ask_user menu (ignored for
    plan_review; the server drops any pick not actually offered). The engine-only
    ``timeout`` is never sent by a client.
    """

    decision: CheckpointDecision
    note: str = Field("", max_length=4000)
    selected: list[str] = Field(default_factory=list, max_length=50)


class PendingInteractionSummary(BaseModel):
    """One interaction still awaiting user settlement (journal fold).

    Surfaced on conversation reopen via ``GET .../recovery``. ``payload`` is the
    original ``*_required`` wire payload verbatim. Cold-path pauses stay in ``paused``.
    Includes hot-path (approval / delegation / escalation) and durable ``stage_card``.
    """

    kind: Literal[
        "approval",
        "delegation_authorization",
        "escalation",
        "stage_card",
    ]
    id: str
    message_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PendingApprovalSummary(BaseModel):
    """Deprecated alias for import compatibility during P1; prefer PendingInteractionSummary."""

    approval_id: str
    conversation_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class PausedTurnSummary(BaseModel):
    """A turn awaiting resume after a durable plan_review / ask_user / kickoff pause.

    Surfaced on conversation reopen so the client can re-render the right resume card
    by ``kind`` and offer the kind-appropriate actions → the resume endpoint
    (kickoff delegate: continue[+嘱咐] / stop; debate: continue / adjust / stop;
    plan_review: continue / adjust / stop).
    ``message_id`` is both the pause key and the id the resumed assistant message will
    reuse, so an optimistic bubble reconciles cleanly.

    plan_review carries ``steps`` (the reviewed checkpoint nodes) + ``pending`` (the
    gated downstream); team_preview (开工卡) carries ``primitive`` (``delegate`` /
    ``debate``) + ``workers`` / ``tools`` (delegate) or ``motion`` / ``sides`` /
    ``max_rounds`` / ``thorough`` (debate); ask_user carries the unified card payload
    ``question`` (the framing / opening line) + ``context`` + the optional opening
    content ``assumptions`` / ``questions`` (empty for a compact mid-task fork). The
    unused set is empty for the other kinds.
    """

    message_id: str
    kind: SuspensionKind
    checkpoint_id: str
    user_message: str = ""
    # Client-minted id of the user bubble (sidecar write-back pins the persisted row).
    user_message_id: str = ""
    # plan_review
    steps: list[dict[str, Any]] = Field(default_factory=list)
    pending: list[dict[str, Any]] = Field(default_factory=list)
    # team_preview (开工卡)
    workers: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    primitive: str = "delegate"
    motion: str = ""
    form: str = ""
    sides: list[dict[str, Any]] = Field(default_factory=list)
    max_rounds: int = 0
    thorough: bool = True
    # ask_user
    question: str = ""
    context: str = ""
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    intent: AskCheckpointIntent | None = None


class TurnRecoveryResponse(BaseModel):
    """One-shot recovery snapshot for a conversation reopen (recovery 统一, 对称 §8.2).

    Reopen needs to know, from ONE owner-gated point-in-time read, how to recover the
    conversation's latest turn:

    - ``live_running``: a detached in-flight run is still alive to 续看 (实时重连续看
      C1 · slice 1b) — the client attaches (``GET .../stream``) to replay + tail it.
    - ``paused``: turns that durably paused at a plan_review / ask_user checkpoint and
      lost their live stream (结构化挂起 2b) — each renders a resume card.
    - ``pending_interactions``: hot-path interactions still awaiting settlement
      (journal fold: approval / delegation_authorization / escalation).
      Cold-path stays in ``paused``.
    """

    live_running: bool = False
    paused: list[PausedTurnSummary] = Field(default_factory=list)
    pending_interactions: list[PendingInteractionSummary] = Field(default_factory=list)


class Citation(BaseModel):
    """A web source consulted for an assistant message (source-card data).

    Optional ``id`` / ``date`` / ``tier`` / ``query`` / ``deep_read`` / ``registrant`` /
    ``citable`` support the debate evidence ledger (M1), source-card credibility
    badges, and 引用即出处 P1 台账溯源。``tier`` is forward-compatible
    (``official`` / ``media`` / ``unknown`` / ``weak``; ``blocked`` never reaches the
    wire). Absent fields on legacy cards → client degrades.
    """

    url: str
    title: str = ""
    snippet: str = ""
    site: str = ""
    id: str | None = None
    date: str | None = None
    tier: str | None = None
    query: str | None = None
    deep_read: bool | None = None
    registrant: str | None = None
    citable: bool | None = None


class EvidenceLedgerEntryRest(BaseModel):
    """回合调研台账条目（REST / 落库；与 SSE ``TurnEvidenceLedgerEntry`` 同形）。"""

    id: str
    url: str = ""
    title: str = ""
    snippet: str = ""
    site: str = ""
    date: str = ""
    tier: str = "unknown"
    query: str = ""
    deep_read: bool = False
    selected: bool = False
    doc_kind: str = ""
    registrant: str = ""
    citable: bool = True


class RunError(BaseModel):
    """A turn's terminal error (报错回合), projected from the journal's ``turn_end``
    outcome fact so the inline error card replays on reload (Tier 2 a).

    Live, the error rides a transport-only ``error`` SSE event (never journaled), so
    persisting ``code`` + ``message`` on the outcome fact is its only durable home.
    ``code`` drives the bubble's retry affordance; ``message`` is the user-facing text
    the card shows — the same pair the live ``error`` event carried.
    """

    code: str
    message: str


class RunsPayload(BaseModel):
    """Persisted turn replay payload for an assistant message.

    ``events`` is a multi-agent turn's ordered run/tool SSE events; the client
    replays them through the same fold as the live stream to reproduce the team
    graph exactly on reload (empty ``[]`` for a single-agent turn). ``process`` is
    a single-agent turn's 思考+工具 timeline (ordered reasoning/tool steps) the
    client replays into the inline process panel; ``null`` unless the turn used a
    tool. ``run_processes`` is the per-worker-run ProcessStep[] map (对称 CEO
    ``process``) so run-detail timelines reopen with the same interleaving as live;
    ``null`` when no worker produced a timeline. ``captain_context`` is the CEO
    captain's received context (上下文传递可视化 通道①: ``system`` / ``history`` /
    ``request``), turn-level so it replays on the CEO bubble even for a pure-chat
    turn (where ``events`` is empty); ``null`` unless the captain shipped context.
    ``error`` is a 报错回合's terminal error, replaying the inline error card on
    reload (``null`` for a clean turn). ``null`` whole payload on messages with
    none of these.
    """

    events: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    process: list[dict[str, Any]] | None = None
    # Per-worker-run 思考·正文·工具 timeline (run_id → ProcessStep[]). Symmetric to
    # turn-level ``process`` for the CEO bubble; reload seeds each run's detail panel
    # so live / reopen interleaving match. null when no worker produced a timeline.
    run_processes: dict[str, list[dict[str, Any]]] | None = None
    captain_context: list[dict[str, Any]] | None = None
    error: RunError | None = None
    # 预检警告（P2 DURABLE）：journaled ``turn_warning`` lifted like captain_context so a
    # plain-chat turn (no surface events) still replays the banner on reload. null when none.
    turn_warning: str | None = None


class TurnCollabMetrics(BaseModel):
    """Per-turn orchestration signals (学·度量 §2.5) — the user-facing slice of turn_metrics.

    Persisted in the assistant row's ``usage`` JSON column (nested under ``collab``) and
    replayed on reload; live, they ride ``message_end``. Orchestration counts surface in
    the assistant footer for all users; ``audit_drops`` is 诊断模式-only (采集降级).
    """

    boundary_yields: int = 0
    scope_signals: int = 0
    revises: int = 0
    escalations: int = 0
    audit_drops: int = 0


class MessageDetail(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str | None
    reasoning_content: str | None = None
    # trace_id 关联气泡↔日志: the turn's log correlation id (messages.trace_id column),
    # surfaced so a reloaded bubble can copy it for one-step log lookup — live it rides
    # the message_start event. NULL for user / untraced (handoff) rows. Auto-populated
    # from the ORM attribute via from_attributes.
    trace_id: str | None = None
    attachments: list[StoredAttachment] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    # 回合调研台账（引用即出处 P1, DERIVED）：live 走 ``evidence_ledger`` SSE；落库
    # ``messages.evidence_ledger``。缺字段 / [] = legacy。不含辩论场级台账。
    evidence_ledger: list[EvidenceLedgerEntryRest] = Field(default_factory=list)
    # 回合级「下一步推荐」chips (下一步推荐, DERIVED 持久化): the assistant row's persisted
    # quick-reply suggestions (messages.followups column), surfaced so reopening a
    # conversation replays the last turn's chips — live they ride followups_generated.
    # Auto-populated from the ORM attribute via from_attributes. [] for user / none-minted.
    followups: list[str] = Field(default_factory=list)
    runs: RunsPayload | None = None
    # 回合 token 用量 + 轮次 (Tier 2 重载持久化): the assistant row's ``usage`` column carries
    # the turn's token snapshot + rounds; surfaced so the bubble's meta row (用量 + 轮次)
    # replays on reload — live, they ride ``message_end``. ``usage`` is projected from the
    # column's long-key snapshot to the ledger short-key {@link UsageBreakdown} via the
    # validator below; ``rounds`` shares the column but has no own attribute, so the read
    # route sets it. Both ``null`` for user / pre-feature rows (and ``usage`` for an
    # errored / empty turn that spent no tokens — parity with the live bubble's omission).
    usage: UsageBreakdown | None = None
    rounds: int | None = None
    # 回合墙钟用时 (主回复 meta)：与 message_end.duration_ms / turn_metrics 同锚；
    # 写入 usage JSON，读路径投影。null for user / pre-feature rows.
    duration_ms: int | None = None
    # Progressive assistant-row lifecycle (messages.usage.status): running / complete /
    # incomplete / failed. Projected on read like ``rounds`` (not part of UsageBreakdown).
    # In-flight turns carry ``running`` + may hold partial content/reasoning (P1 overlay
    # fills those from turn_stream_state). null for user / pre-feature rows.
    status: Literal["running", "complete", "incomplete", "failed"] | None = None
    # Cold-path pause latch (messages.usage.paused): write side keeps ``status=running`` +
    # ``paused:true`` so overlay/promotion still treat the row as the live latch; read
    # lifts the flag so clients hydrate as paused (not streaming). null/false otherwise.
    paused: bool | None = None
    # Message provenance stamped into ``usage`` JSON (e.g. ``execution_harvest`` for
    # system closing-turn synthetic user rows). Projected on read like ``rounds`` —
    # the UsageBreakdown validator strips non-token keys, so clients cannot recover
    # origin from ``usage`` alone. null for ordinary user / assistant rows.
    origin: str | None = None
    # 协作质量 (学·度量 §2.5, 诊断模式): orchestration signals nested in the usage column;
    # projected on read like ``rounds``. null for single-agent / pre-feature rows.
    collab: TurnCollabMetrics | None = None
    # 回复反馈 (点赞/点踩, 对话基础功能补齐): the user's satisfaction signal on this assistant
    # reply — "up" | "down" | null(未评价). Auto-populated from the ORM attribute via
    # from_attributes so a reloaded bubble replays the user's rating. null for user rows.
    feedback: str | None = None
    # 回合 ¥ 成本 (P2 DERIVED)：messages.cost 列快照；读路径补 cny_total（元 = nano/1e9）。
    # null for user / unmetered / pre-feature rows. Hover payroll still uses GET …/cost.
    cost: CostBreakdown | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("usage", mode="before")
    @classmethod
    def _usage_from_row(cls, v: object) -> object:
        # The ORM ``usage`` column is a long-key snapshot ({input_tokens, …, rounds}).
        # Project it to the short-key UsageBreakdown the client reads; show tokens only
        # when the turn reported real spend (an errored / empty turn stored zeros, which
        # the live bubble also omits). A value already in UsageBreakdown shape passes
        # through unchanged (so model construction outside from_attributes still works).
        if isinstance(v, dict):
            if not (v.get("input_tokens") or v.get("output_tokens")):
                return None
            return {
                "input": v.get("input_tokens", 0),
                "output": v.get("output_tokens", 0),
                "reasoning": v.get("reasoning_tokens", 0),
                "cache_hit": v.get("cache_hit_tokens", 0),
                "cache_miss": v.get("cache_miss_tokens", 0),
            }
        return v

    @field_validator("cost", mode="before")
    @classmethod
    def _cost_from_row(cls, v: object) -> object:
        # Column stores nano-CNY components (+ currency); attach display yuan via
        # nano_to_yuan (parity with cost_view.cost_breakdown).
        if isinstance(v, dict) and "cny_total" not in v:
            from agentcore.api.cost_view import cost_breakdown

            return cost_breakdown(v)
        return v


class MemoryUpdateItemView(BaseModel):
    """One applied memory change in a 记忆已更新 card (Agent记忆与知识系统 §1.6).

    ``file`` is a friendly label (偏好 / 画像 / 主题·<slug>); ``scope`` is ``global`` or
    ``project`` (the conversation's project layer); ``content`` is the bullet text for an
    add/update or the matched text for a remove. ``target`` is the synthetic memory-leaf
    path the card deep-links to (desktop ``memorySource`` scheme; "" = no leaf).
    ``project_id`` is the folder id when scope is project (最近更新 deep-link). Shape
    mirrors ``memory/maintenance.py`` ``MemoryUpdateItem`` (the stored
    ``memory_updates.items`` JSONB)."""

    action: str
    file: str
    section: str = ""
    scope: str = "global"
    content: str = ""
    target: str = ""
    project_id: str | None = None


class MemoryUpdateView(BaseModel):
    """One memory-write notice for the conversation-tail card (two-layer memory).

    Projected from a ``memory_updates`` row. ``kind`` selects the UI:
    - ``episodic``: light tip; ``summary`` is the ≤200-char session digest; ``items`` empty.
    - ``semantic``: diff card; ``items`` lists add/update/remove bullets.

    Returned only with the LATEST messages window, and pushed live on the per-user firehose.
    """

    id: str
    kind: str = "semantic"
    summary: str | None = None
    items: list[MemoryUpdateItemView] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    """A window of a conversation's messages (chronological, oldest-first).

    Cursor-windowed rather than page-numbered: the client loads the latest window
    on open, then scrolls up (``before``) / down (``after``), or jumps to a window
    centered on a message (``around``) for a search hit. ``has_more_before`` /
    ``has_more_after`` tell the client whether to keep fetching in that direction.
    Only the direction-relevant flag is computed for a one-sided query (a
    ``before`` page sets ``has_more_after=False``; the client already holds the
    newer side); an ``around`` window computes both.

    ``memory_updates`` carries the conversation's 记忆已更新 cards (记忆更新对话内可见,
    §1.6) — populated ONLY for the latest window (the cards sit at the thread tail, after
    the last message); empty on scroll-up/around pages and when nothing was consolidated.
    """

    data: list[MessageDetail]
    total: int
    has_more_before: bool = False
    has_more_after: bool = False
    memory_updates: list[MemoryUpdateView] = Field(default_factory=list)


# --- Local turn recording (双模式工作区 §一.1: sidecar 本地引擎回合回传落库) ---
# A turn run by the local sidecar engine produced its reply on the user's machine —
# no server pipeline ran — so the desktop reports the finished turn here to land it
# in durable history (入库 / 跨设备) AND in the cost ledger (计费回写). Workspace
# snapshots stay out of scope (local files live on the user's disk; the local→云
# handoff is the separate explicit bridge).


class RecordTurnRequest(BaseModel):
    """A finished local (sidecar) turn to persist: the user message + assistant reply.

    Carries the assistant outcome the local pipeline returned (content / reasoning /
    citations / replay ``runs`` / the pipeline ``message_id`` so streamed and stored
    ids agree). The FULL token snapshot rides on ``Message.usage`` (input / output /
    reasoning / cache hit / cache miss + rounds) so a reloaded sidecar turn's meta row
    matches a cloud turn's. Spend is NOT sent: a sidecar turn's LLM calls are metered
    authoritatively at the cloud inference proxy (``/v1/inference``, Slice 4a), so this
    write-back persists content only.
    """

    user_message: str = Field(..., min_length=1, max_length=32000)
    content: str = Field("", max_length=500_000)
    reasoning_content: str | None = Field(None, max_length=500_000)
    citations: list[Citation] = Field(default_factory=list, max_length=50)
    # 引用即出处 P1 · Q9：与云路径同形落盘；缺字段 legacy 降级。
    evidence_ledger: list[EvidenceLedgerEntryRest] = Field(default_factory=list, max_length=200)
    runs: RunsPayload | None = None
    # Progressive outbox journal facts (``{kind, payload, ts}``), ordered by seq.
    # Optional + backward-compatible: crash/cancel salvage often has no ``runs``
    # projection, only the mid-turn ``outbox.journal`` map — finalize persists these
    # directly when ``runs`` is absent. Happy-path write-back still sends ``runs``.
    journal: list[dict[str, Any]] | None = None
    # The client-minted id of the user bubble (a clean UUID). Pinning the persisted
    # user row to it makes the whole write-back idempotent: the desktop retries this
    # POST on a flaky response, and a retry after a write we DID commit must not
    # duplicate the user/assistant rows (双模式工作区 §一.1 回写可靠性).
    user_message_id: str = Field(..., min_length=1, max_length=64)
    message_id: str | None = Field(None, max_length=64)
    # Full usage snapshot — persisted verbatim into ``Message.usage`` to match the cloud
    # turn's 6-key row (cloud ``persist_turn_result``). reasoning / cache tokens are additive
    # (default 0), so an older desktop that omits them degrades to today's partial snapshot.
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    reasoning_tokens: int = Field(0, ge=0)
    cache_hit_tokens: int = Field(0, ge=0)
    cache_miss_tokens: int = Field(0, ge=0)
    rounds: int = Field(0, ge=0)
    # The local turn's trace_id (32-hex), stamped by the desktop on every cloud
    # inference-proxy LLM call this turn made. Reusing it for the persisted reply joins
    # the reasoning logs + the bubble under ONE trace (打通气泡↔日志).
    trace_id: str = Field(..., min_length=32, max_length=32)
    # Pipeline finish reason (``FinishReason`` value). ``paused`` / ``error`` skip title +
    # memory consolidation and upsert the assistant snapshot in place (挂起即收口 ②).
    finish_reason: str | None = Field(None, max_length=32)


class RecordTurnResponse(BaseModel):
    """The persisted ids for a recorded local turn (the desktop reconciles its
    optimistic user/assistant bubbles against these; ``title`` is set only when this
    turn minted the conversation's first title; ``followups`` mirrors the live
    ``followups_generated`` chips when this turn minted them).

    ``noop=True`` means the server intentionally skipped an assistant row (empty
    body + no process state). Desktop may delete the outbox only when
    ``assistant_message_id`` is set **or** ``noop`` is True — never on a bare null id
    when the turn carried runs/journal/segments.
    """

    user_message_id: str
    assistant_message_id: str | None = None
    title: str | None = None
    followups: list[str] | None = None
    noop: bool = False


class StopTurnResponse(BaseModel):
    """Outcome of an explicit 停止 (执行与请求解耦 C1 · slice 1a).

    ``stopped`` is True when a live detached run was found and signalled; False when
    nothing was running (already finished / never started), so the call is idempotent.
    """

    stopped: bool
