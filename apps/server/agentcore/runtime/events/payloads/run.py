"""Multi-agent run SSE payload wire models (factories: ``runtime/events/run.py``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from agentcore.runtime.events.payloads._base import WirePayload, absent
from agentcore.runtime.events.payloads.chat import ResetReason
from agentcore.runtime.events.payloads.shared import CostBreakdown, RunDebrief, UsageBreakdown
from agentcore.runtime.runs.types import RunKind

Stance = Literal["pro", "con"]
EscalationKind = Literal["normal", "scope", "dep"]
PlanRevisionKind = Literal["bind", "steer"]
# 幕类型 = 能力档取用键（首批 multi_agent / debate；single_agent 不进幕序列）。
ActKind = Literal["multi_agent", "debate"]
# 幕授权来源（批 B）：推进卡点开辩 / 自动开辩 / 开工卡确认。
ActAuthorizedBy = Literal["stage_card", "auto", "preview"]


class PlanRevision(WirePayload):
    run_id: str
    kind: PlanRevisionKind


class PlanRevisedPayload(WirePayload):
    execution_id: str
    revisions: list[PlanRevision]


class PlanAgentPayload(WirePayload):
    id: str
    role: str
    thinking: bool


class RunPlanRunEntry(WirePayload):
    id: str
    agent_id: str
    task: str
    depends_on: list[str]
    parent_run_id: str | None = absent()
    kind: RunKind | None = absent(ts_type="RunKind")
    stance: Stance | None = absent()
    # 呈现分组权威：计划内节点的 ``group`` 以本字段为准（三端 fold 从 run_plan 物化）；
    # 首跑 ``run_started``（``execute_agent_node``）不重复携带。续写身份见 ``RunStartedPayload``。
    group: str | None = absent()
    round: int | None = absent()
    replaces_run_id: str | None = absent()


class RunPlanAct(WirePayload):
    """幕声明（批 A1）：一张 execution 图由 1..N 幕组成；本批仅首幕 act-1。

    runs 归属 = 该 run_plan 声明的幕（``RunPlanRunEntry`` 不加字段）。
    ``authorized_by``（批 B）：辩论幕的授权来源；调研幕缺省。
    """

    act_id: str
    kind: ActKind
    title: str | None = absent()
    # 本幕从宿主图哪个节点后长出；首幕缺省。
    anchor_run_id: str | None = absent()
    authorized_by: ActAuthorizedBy | None = absent()


class RunPlanPayload(WirePayload):
    execution_id: str
    plan_type: Literal["single_agent", "multi_agent", "debate"]
    task_summary: str
    agents: list[PlanAgentPayload]
    runs: list[RunPlanRunEntry]
    # 跨回合同图追加：生长帧归属的宿主助手消息（= 旧协作图所在 turn_id）。
    # 缺省 = 本回合新建图（同回合二次 delegate 亦不带此字段，靠同 execution_id merge）。
    host_message_id: str | None = absent()
    # 幕声明（additive）：旧客户端 / 旧 journal 忽略；缺省时前端 fold 合成 act-1。
    act: RunPlanAct | None = absent()


class GraphAppendPayload(WirePayload):
    """跨回合同图追加锚点——落在【追加回合】journal；生长内容续写宿主 turn。"""

    execution_id: str
    host_message_id: str
    append_message_id: str
    added_count: int
    roles: list[str] = Field(default_factory=list)
    added_run_ids: list[str] = Field(default_factory=list)
    # 幕归属（additive）：文案区分「开新幕」vs「同幕补派」属后续批次；本批只透传字段。
    act_id: str | None = absent()
    act_kind: ActKind | None = absent()
    # 开幕授权来源（批 B，与 RunPlanAct.authorized_by 同形）。
    authorized_by: ActAuthorizedBy | None = absent()


class RunStartedPayload(WirePayload):
    run_id: str
    agent_id: str
    parent_run_id: str | None
    kind: RunKind
    # 同人续派 / 热修 / 辩论续写：恒指现场根（RunSession 键）；星型，前端铺链。
    continues_run_id: str | None = absent()
    stance: Stance | None = absent()
    # 仅续写路径（``continue_run`` / 证人答问）携带：未入 plan 的续写靠本字段出生身份。
    # 计划内首跑（取证员 / 首轮辩手等经 ``execute_agent_node``）不带——
    # ``group`` 权威 = ``run_plan``。
    group: str | None = absent()
    round: int | None = absent()
    # 辩论续写语义方 key（质询 / 结辩 / 续轮）；缺字段（老 journal）→ 前端按 stance / sides 回退。
    side_key: str | None = absent()
    replaces_run_id: str | None = absent()


ContextChannel = Literal[
    "system",
    "history",
    "request",
    "team_position",
    "dependency",
    "workspace",
    "task",
    "deliverable",
    "team_brief",
    "gate_notes",
    "steer",
    "team_result",
    "round_focus",
    "opponent",
    "challenge",
    "interjection",
    "continuation",
    "cross_exam",
    "witness_exam",
    "closing",
    "attack",
    "defense",
    "rebuttal",
    "thread",
    "crux",
]
ContextFidelity = Literal["", "pointer", "summarize", "pass_through"]


class ContextBlockWire(WirePayload):
    channel: ContextChannel
    heading: str
    body: str
    chars: int
    truncated: bool
    source_role: str
    source_run_id: str
    fidelity: ContextFidelity
    files: list[str]


class RunContextPayload(WirePayload):
    run_id: str
    agent_id: str
    blocks: list[ContextBlockWire]


class RunOutputDeltaPayload(WirePayload):
    run_id: str
    agent_id: str
    delta: str


class RunOutputResetPayload(WirePayload):
    run_id: str
    agent_id: str
    # 与 ContentResetPayload.reason 同一枚举：仅 finish_guard 折出 rework 痕迹（didRework）。
    reason: ResetReason = Field(json_schema_extra={"ts_type": "ResetReason"})


class RunReasoningDeltaPayload(WirePayload):
    run_id: str
    agent_id: str
    delta: str


class RunToolProgressPayload(WirePayload):
    run_id: str
    agent_id: str
    tool_name: str
    chars: int


class RunEscalationPayload(WirePayload):
    """升级实时可见 (非阻塞 raised): a worker flagged a decision/blocker and kept working.

    JOURNALED (DURABLE, 统一时间线二期 D6): ``escalation_id`` keys the raised 轻行's
    timeline marker (幂等去重 on attach replay) and lets the raised row + node ⚠️ badge
    reload — the event base is now level with ``escalation_required``.
    """

    escalation_id: str
    run_id: str
    agent_id: str
    question: str
    assumption: str
    blocking: bool
    kind: EscalationKind | None = absent()


class RunEscalationGatePayload(WirePayload):
    run_id: str
    agent_id: str
    layer: Literal["execution", "scheme"]
    action: Literal["continue", "escalate"]
    signals: list[dict[str, Any]]


class TeamNotePostedPayload(WirePayload):
    execution_id: str
    note_id: str
    run_id: str
    agent_id: str
    role: str
    kind: Literal["decision", "heads_up", "claim"]
    text: str
    ts: float
    supersedes: str | None = absent()
    supersede_mode: Literal["update", "void"] | None = absent()
    source: Literal["ceo", "worker", "inherited"] | None = absent()


class TeamSynthesisWorkerPreview(WirePayload):
    run_id: str
    role: str
    status: Literal["pending", "completed", "failed", "cancelled"]
    summary: str


class TeamSynthesisPreviewPayload(WirePayload):
    execution_id: str
    completed: int
    total: int
    headline: str
    text: str
    workers: list[TeamSynthesisWorkerPreview]
    in_progress: bool


class CoordinationWaitPayload(WirePayload):
    """CEO 协调等待（``coordination_wait``）：captain 空等团队事件时的前端 UX 信号。

    ``waiting=true`` 进入/心跳刷新；``waiting=false`` 清除。``completed``/``total`` 为
    session 计数（已完成 worker / 总 worker）。EPHEMERAL——不落 journal。
    """

    execution_id: str
    waiting: bool
    completed: int
    total: int


DeliveryState = Literal["delivered", "partial", "blocked", "notes"]


class DeliveryGap(WirePayload):
    """One undelivered piece in the wrap-up reconciliation (交付诚实性): the worker
    ``role`` it belongs to (or a batch-level label like「验收」) + a one-line
    ``description`` of what never landed (contract shortfall / degraded handoff /
    completion criteria unmet / failed worker).

    Optional ``reason`` is a machine-readable cutoff / shortfall code when the gap
    comes from a structured engine signal — known:
    ``token_budget`` / ``worker_timeout`` / ``degraded_handoff`` /
    ``unverified_note`` (soft 待核实/示例自注) /
    ``files_not_landed`` (零落盘：worker 契约与批次 files_written 合并投影) /
    ``verify_failed`` (验证形工具失败：browser_navigate / test_run /
    verify 形 code_execute·terminal).
    Absent for ordinary contract / criteria prose gaps that have not been projected.
    Clients may badge known codes and ignore unknown ones (forward-compatible).

    Optional ``severity``: ``warning`` = soft reminder (待核实等，不单独撑起
    partial/blocked); absent or ``blocking`` = real shortfall. Old clients that
    ignore unknown fields still see the row; new clients split summary / card state.

    Optional ``paths``: workspace-relative files implicated by a soft note (for
    「打开相关文件」); absent on ordinary blocking gaps."""

    role: str
    description: str
    reason: str | None = absent()
    severity: Literal["blocking", "warning"] | None = absent()
    paths: list[str] | None = absent()


class DeliveryAction(WirePayload):
    """One user action that would close a delivery gap. ``kind`` is a widened string
    on the wire (like ``ToolPhase``) so the backend can add kinds without a client
    bump — known: ``bind_local_folder`` (云端无执行环境 → 绑定本机执行环境后可运行生成；≠打开项目);
    ``export_to_local`` (云端已有 delivered_files → 导出到本机文件夹后即可 npm install / 本地运行；
    与 bind_local_folder 可并存但语义不同);
    ``website_verify`` (整页 QA 因预算 defer → 一键续派 ``build_website_verify``);
    ``continue_skipped_runs`` (turn/nested 额度 SKIPPED 未跑节点 → 下一回合续跑);
    unknown kinds render as a plain hint.
    （成篇未写完改由对话框接着说——已撤 ``continue_writing`` 一键按钮。）

    Optional ``prompt`` is the exact user-turn text a client should send for
    kinds that open a new message (e.g. ``website_verify``). Absent for
    non-message actions like ``bind_local_folder`` / ``export_to_local``."""

    kind: str
    description: str
    prompt: str | None = absent()


class DeliveryArtifact(WirePayload):
    """One path-level acceptance row on ``delivery_status`` (主清单数据源).

    ``status=accepted`` → counts toward ``delivered_files`` / CEO「已交付」;
    ``rejected`` carries ``reason`` (e.g. ``citations_unverified``) and optional
    ``detail`` for the file checklist. Draft is out of scope for block 1.
    """

    path: str
    status: Literal["accepted", "rejected"]
    reason: str | None = absent()
    detail: str | None = absent()


class DeliveryStatusPayload(WirePayload):
    """交付状态（能力闸门与交付诚实性）: the structured delivery reconciliation a
    delegate batch emits at wrap-up — 已交付文件 / 缺口 / 待用户操作 — so the client
    renders an honest delivery card instead of mining the CEO's prose. Folds keep the
    LATEST per ``execution_id`` (reflects the most recent batch's reconciliation).
    ``state``: delivered = 无 blocking 缺口且有落盘产物; partial = 有产物也有
    blocking 缺口; blocked = 有 blocking 缺口且无落盘产物;
    notes = 仅有 soft 待核实提醒（轻提醒，非「部分未满足」）。
    ``artifacts``: path-level acceptance (accepted+rejected); ``delivered_files``
    remains accepted-only for older clients."""

    execution_id: str
    state: DeliveryState
    summary: str
    delivered_files: list[str]
    gaps: list[DeliveryGap]
    actions: list[DeliveryAction]
    artifacts: list[DeliveryArtifact] = []


class UserInterjectionAttachment(WirePayload):
    """Attachment metadata on a mid-flight interjection (no inline text body)."""

    name: str
    workspace_path: str | None = absent()
    binary: bool = False


class UserInterjectionPayload(WirePayload):
    """Mid-flight user message into a live coordination turn (CEO routes)."""

    interjection_id: str
    execution_id: str
    content: str
    status: Literal["delivered", "queued"]
    note: str | None = absent()
    attachments: list[UserInterjectionAttachment] | None = absent()


class TurnQueuedPayload(WirePayload):
    """FIFO queue ack on the send SSE while another turn is in-flight (D9 · 发送即有流).

    Replaces the retired HTTP 202 ``SendMessageQueuedResponse`` JSON. Same visibility
    fields; the waiting connection later continues with the drained turn on this stream.
    """

    queue_id: str
    position: int
    queue_depth: int
    conversation_id: str


class ExecutionDetachedPayload(WirePayload):
    """执行转后台（``execution_detached``）：附着回合已收口，团队继续跑。"""

    execution_id: str
    conversation_id: str
    completed: int
    total: int
    reason: str | None = absent()
    host_turn_id: str | None = absent()


class ExecutionCompletedPayload(WirePayload):
    """后台执行终态（``execution_completed``）：drive 到齐、收割者可发起收口。"""

    execution_id: str
    conversation_id: str
    completed: int
    total: int
    host_turn_id: str | None = absent()
    error: str | None = absent()


class RunCompletedPayload(WirePayload):
    run_id: str
    agent_id: str
    output_summary: str
    duration_ms: int
    role: str
    model: str
    usage: UsageBreakdown
    cost: CostBreakdown
    debrief: RunDebrief | None = absent()
    output_files: list[str] | None = absent()
    # Soft-accept / cutoff gaps on a COMPLETED node (additive). Same shape as
    # ``DeliveryGap`` minus the batch-level ``role`` (node role is on the payload).
    gaps: list[DeliveryGap] | None = absent()
    # Host-journal routing after turn teardown (pillar A); absent on old fixtures.
    execution_id: str | None = absent()


class RunFailedPayload(WirePayload):
    run_id: str
    agent_id: str
    error: str
    debrief: RunDebrief | None = absent()
    execution_id: str | None = absent()


class RunCancelledPayload(WirePayload):
    run_id: str
    agent_id: str
    reason: Literal["redirect", "stop"]
    execution_id: str | None = absent()


class RunSkippedPayload(WirePayload):
    run_id: str
    agent_id: str
    reason: Literal["cascade", "abort"]


class RunProgressPayload(WirePayload):
    completed: int
    total: int


class NodeTimingPayload(WirePayload):
    run_id: str
    start_ms: int
    end_ms: int
    outcome: str


class BatchMetricsPayload(WirePayload):
    execution_id: str
    nodes: int
    width: int
    peak_running: int
    wall_ms: int
    busy_ms: int
    slot_starved: int
    completed: int
    failed: int
    skipped: int
    cancelled: int
    bind_boundaries: int
    scope_boundaries: int
    checkpoint_boundaries: int
    escalations: int
    scope_escalations: int
    timeline: list[NodeTimingPayload]


# Registry alias (events.ts names this inline run-plan row type).
RunPlanNode = RunPlanRunEntry

# Re-export shared leaf types referenced by ``payloads/__init__.py`` TS_EXPORTS.
