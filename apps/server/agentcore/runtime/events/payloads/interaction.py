"""User-interaction SSE payload wire models (factories: ``runtime/events/interaction.py``).

Decision enums are reused from their runtime owners (``runtime/approvals.py`` /
``runtime/checkpoints.py``) so the wire contract and the gate logic share one source.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from agentcore.runtime.approvals import ApprovalDecision, DelegationAuthorizationDecision
from agentcore.runtime.checkpoints import AskCheckpointIntent, CheckpointDecision
from agentcore.runtime.debate.types import DebateForm
from agentcore.runtime.events.payloads._base import WirePayload, absent
from agentcore.runtime.events.payloads.run import EscalationKind
from agentcore.runtime.events.payloads.shared import MotionCardSide


class ApprovalRequiredPayload(WirePayload):
    approval_id: str
    conversation_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ApprovalResolvedPayload(WirePayload):
    approval_id: str
    tool_call_id: str
    decision: ApprovalDecision


class DelegationAuthorizationWorker(WirePayload):
    """One worker row on the delegation authorization card (role + task preview)."""

    role: str
    task: str


class DelegationAuthorizationRequiredPayload(WirePayload):
    """A delegate batch paused awaiting the user's delegation-level tool authorization
    (委派级授权). Medium-risk tools in `tools` are the grant scope."""

    authorization_id: str
    conversation_id: str
    execution_id: str
    workers: list[DelegationAuthorizationWorker]
    tools: list[str]


class DelegationAuthorizationResolvedPayload(WirePayload):
    authorization_id: str
    execution_id: str
    decision: DelegationAuthorizationDecision


class AskAssumption(WirePayload):
    id: str
    label: str
    value: str


class AskOption(WirePayload):
    """One selectable answer to a choice AskQuestion. `label` is both the displayed text
    and the value composed back into the answer; `recommended` is advisory highlight only
    (NOT a pre-selection). `action` marks an option that the desktop client fulfils with a
    native client action instead of a plain text answer (unknown/absent → plain option):
    `open_local_project` renders as a folder picker that creates/reuses a local Folder
    (mode=local, empty subpath, root=chosen dir) and starts a **new** conversation under
    that project — never rewrites the current session's ``folder_id``;
    `bind_local_folder` renders as a folder picker that binds the bare-chat scratch
    workspace (``conversations/<id>``) for local execution — not 「打开项目」;
    `grant_readonly_folder` renders as a folder picker that grants a session-scoped
    read-only mount under ``external/<alias>/`` (W3; orthogonal to workspace binding —
    cloud scratch + desktop online is enough; does not change binding);
    `grant_organize_folder` is the organize-mode counterpart (move/copy/mkdir/trash-delete).
    Structured ``op`` / ``source`` / ``destination`` / ``path`` fields carry organize_plan
    items for plan-bound ``file_batch``."""

    label: str
    detail: str | None = absent()
    recommended: bool | None = absent()
    action: (
        Literal[
            "open_local_project",
            "bind_local_folder",
            "grant_readonly_folder",
            "grant_organize_folder",
        ]
        | None
    ) = absent()
    op: Literal["move", "copy", "delete", "mkdir"] | None = absent()
    source: str | None = absent()
    destination: str | None = absent()
    path: str | None = absent()


class AskQuestion(WirePayload):
    id: str
    prompt: str
    kind: Literal["choice", "text"]
    options: list[AskOption]
    multiple: bool
    default: str


class AskStyleOption(WirePayload):
    id: str
    label: str


class AskFormatOption(WirePayload):
    id: str
    label: str


class CheckpointRequiredPayload(WirePayload):
    """The CEO paused the turn on an ask_user checkpoint (blocking)."""

    checkpoint_id: str
    conversation_id: str
    question: str
    context: str
    assumptions: list[AskAssumption]
    questions: list[AskQuestion]
    style_options: list[AskStyleOption]
    format_options: list[AskFormatOption] = Field(default_factory=list)
    intent: AskCheckpointIntent | None = absent(ts_type="CheckpointIntent")


class CheckpointResolvedPayload(WirePayload):
    checkpoint_id: str
    decision: CheckpointDecision
    note: str
    selected: list[str] | None = absent()


class QuestionPostedPayload(WirePayload):
    """A non-blocking ask the CEO posted (ask_user blocking=false): it already has a
    default and KEPT WORKING — no suspend, no resolve."""

    ask_id: str
    conversation_id: str
    question: str
    context: str
    assumptions: list[AskAssumption]
    questions: list[AskQuestion]
    style_options: list[AskStyleOption]
    format_options: list[AskFormatOption] = Field(default_factory=list)


class PlanReviewStep(WirePayload):
    run_id: str
    role: str
    summary: str


class PlanReviewPending(WirePayload):
    run_id: str
    role: str


class CeoReviewSummary(WirePayload):
    """主 Agent 在 plan_review 前对本波产出的把关摘要
    （拍板卡展示；继续时 llm 压缩注入 gate_notes）。"""

    conclusion: str
    risks: list[str]
    suggestions: list[str]
    source: Literal["llm", "deterministic"] | None = absent(
        "把关来源；旧帧缺省。仅 llm 在 CONTINUE 时压缩注入 gate_notes。"
    )


class PlanReviewRequiredPayload(WirePayload):
    checkpoint_id: str
    conversation_id: str
    steps: list[PlanReviewStep]
    pending: list[PlanReviewPending]
    ceo_review: CeoReviewSummary | None = absent(
        "CEO 评审前置把关摘要；旧帧 / 旧向量可缺省。"
    )


class PlanReviewResolvedPayload(WirePayload):
    checkpoint_id: str
    decision: CheckpointDecision
    note: str


class TeamPreviewWorker(WirePayload):
    """One upcoming worker row on the thin team-preview card (团队预审)."""

    run_id: str
    role: str
    task: str
    depends_on: list[str]
    debate: bool
    # D4：与 kickoff/summary.worker_rows 对齐；旧 journal 缺字段 → 前端不展示。
    form: str | None = absent("交付形态 prose/files 等；缺省=旧帧。")
    write_capability: Literal["text_only", "can_write_files"] | None = absent(
        "写盘能力判别；由 form 推导。"
    )
    write_capability_label: str | None = absent(
        "写盘能力展示文案（可改文件 / 仅文字报告）。"
    )


class TeamPreviewSide(WirePayload):
    """One debate participant on the debate kickoff card."""

    key: str
    name: str
    stance: str
    is_subject: bool | None = absent()
    # §7.5 真·多模型：三元组；缺字段（老 journal / 同模型场）→ 前端跟 turn 主模型。
    model: str | None = absent("该方辩手模型 id。")
    origin: Literal["platform", "byok"] | None = absent("模型来源。")
    provider_id: str | None = absent("BYOK 服务商 id；platform 缺省。")


class ModelCandidate(WirePayload):
    """§7.5 D：消歧零/多候选时开赛卡 / 错误载荷中的目录行。"""

    model: str
    origin: Literal["platform", "byok"]
    provider_id: str | None = absent()
    label: str | None = absent()
    side_key: str | None = absent("触发消歧的参与方 key；缺省=整场。")


class TeamPreviewRequiredPayload(WirePayload):
    """开工卡：计划预览 + 能力授权（两卡合一）。

    ``primitive`` discriminates ``delegate`` (workers 分工表) vs ``debate``
    (motion / sides / max_rounds). ``tools`` may be empty under full_auto /
    always_ask / debate read-only debaters.
    """

    checkpoint_id: str
    conversation_id: str
    workers: list[TeamPreviewWorker]
    tools: list[str] = Field(default_factory=list)
    primitive: Literal["delegate", "debate"] | None = absent(
        "编排原语判别；缺省按 delegate（旧 journal / 向量兼容）。"
    )
    motion: str | None = absent("辩论辩题；仅 primitive=debate。")
    form: str | None = absent("辩论形态 debate/red_team/roundtable。")
    sides: list[TeamPreviewSide] | None = absent("辩论各方立场。")
    max_rounds: int | None = absent("辩论轮次安全上限（预算展示）。")
    thorough: bool | None = absent("辩论认真辩透 vs 快速对碰。")
    offer_research_first: bool | None = absent(
        "辩论开工卡：本回合零调研时为 true，展示「先多视角调研再辩」；缺省视为 false。"
    )
    research_first_recommended: bool | None = absent(
        "辩论开工卡：零调研且用户输入命中多维取证触发词时为 true，"
        "将「先多视角调研再辩」升为视觉主键；缺省视为 false。"
    )
    # §7.5 裁判选型；缺字段（老 journal）→ 前端不展示裁判行。
    moderator_model: str | None = absent("裁判 / 主持人模型 id。")
    moderator_origin: Literal["platform", "byok"] | None = absent("裁判模型来源。")
    moderator_provider_id: str | None = absent("裁判 BYOK provider_id。")
    same_model_debate: bool | None = absent(
        "目录只剩一模型时为 true，开赛卡明示同模型降级。"
    )
    # §7.5 D：消歧零/多候选目录行；缺字段（老 journal）→ 前端不展示候选区。
    model_candidates: list[ModelCandidate] | None = absent(
        "模型消歧候选（model/origin/provider_id/label）；旧帧缺省。"
    )


class TeamPreviewResolvedPayload(WirePayload):
    checkpoint_id: str
    # continue(=grant[+steer]) / per_call / adjust / stop / research_first / …
    decision: CheckpointDecision
    note: str


class StageCardRequiredPayload(WirePayload):
    """阶段推进卡（批 B）：命题卡升级为可操作交互；幕 1 收尾后耐久展示。

    信息密度 = 最小决策集：命题 + 双方立场 + 形态/轮次默认 + 嘱咐空位。
    ``sides`` 复用 motion 卡薄立场；``thorough`` / ``max_rounds`` 为默认展示（卡上不可改）。
    可选宿主三元组（机制直传，旧客户端忽略）：开辩锚定幕 1 图。
    """

    stage_card_id: str
    conversation_id: str
    motion: str
    sides: list[MotionCardSide]
    form: DebateForm
    rationale: str
    fact_pointers: list[str] = Field(default_factory=list)
    thorough: bool = True
    max_rounds: int = 5
    # Optional empty note slot — client may fill on start_debate; never enters motion gate.
    note: str | None = absent()
    host_execution_id: str | None = absent(
        "幕 1 宿主 execution_id；缺省则开辩时再 resolve_debate_host_attach。"
    )
    synthesizer_run_id: str | None = absent("幕 1 汇总员 run_id（挂点锚）。")
    host_message_id: str | None = absent("幕 1 宿主 turn / message id。")


class StageCardResolvedPayload(WirePayload):
    """推进卡裁决。decision 二值：start_debate（可带 motion_override/note）/ research_first。"""

    stage_card_id: str
    decision: Literal["start_debate", "research_first"]
    note: str = ""
    motion_override: str | None = absent()


class EscalationRequiredPayload(WirePayload):
    """阻塞式求决策 (escalate blocking=true): a delegated worker SUSPENDED itself awaiting
    a decision. JOURNALED (unlike the transport-only `run_escalation` banner); the
    turn never flips to `paused` (siblings keep running).

    ``awaiting``: ``user`` (经典路径，可答卡) or ``ceo`` (协调模式下等主管仲裁，初始不可答)。
    Absent on old journaled events → fold as ``user``.
    """

    escalation_id: str
    run_id: str
    agent_id: str
    question: str
    assumption: str
    questions: list[AskQuestion] | None = absent(
        "Structured forks (同 ask_user 的 questions). Absent on old journaled events "
        "(fold with `?? []`); empty for a free-text ask."
    )
    kind: EscalationKind | None = absent("旧流缺字段时前端按 `normal`。与 blocking 轴正交。")
    awaiting: Literal["user", "ceo"] | None = absent(
        "谁在仲裁：user=经典可答卡；ceo=协调模式等主管。旧流缺字段按 user。"
    )
    browser_login: bool | None = absent(
        "true=用户可在回合仍 running 时接管浏览器完成登录（D16 窄例外）。"
        "旧流缺字段按 false。"
    )
    ownership_paths: list[str] | None = absent(
        "写权冲突路径列表；有值时前端呈现「移交写权 / 保持原主」。旧流缺字段按无。"
    )
    lock_owner_run_id: str | None = absent(
        "当前写权持有者 run_id。旧流缺字段按无。"
    )


class EscalationResolvedPayload(WirePayload):
    """阻塞式求决策 settlement. Emitted by the suspending tool's awaiter ONLY; journaled.

    ``status`` 三分（对 worker 回落假设的实现可共享，对外语义必须分开）：
    - ``resolved`` — 有裁决/答复（``answer`` 非空语义由调用方保证）
    - ``assumed`` — 用户或主管显式选了「按假设继续」
    - ``timed_out`` — 墙钟时限内未答复

    ``arbitrated_by`` / ``via_user`` annotate CEO 协调仲裁可见性（经典用户直答路径可缺省）。
    """

    escalation_id: str
    run_id: str
    agent_id: str
    status: Literal["resolved", "assumed", "timed_out", "orphaned"]
    answer: str
    arbitrated_by: Literal["user", "ceo"] | None = absent(
        "裁决方：user=用户直答；ceo=主管仲裁。旧流缺字段按 user。"
    )
    via_user: bool | None = absent(
        "仅 arbitrated_by=ceo 时有意义：true=主管经 ask_user 转交用户后再 resolve。"
    )


class InteractionOrphanedPayload(WirePayload):
    """pending 交互失效（假卡消灭）。含热路 kind + 推进卡 stage_card。"""

    interaction_id: str
    kind: Literal[
        "approval",
        "delegation_authorization",
        "escalation",
        "debate_round",
        "stage_card",
    ]
    reason: str | None = absent(
        "可选失效原因（如 stage_card superseded）；缺省不传，旧客户端忽略。"
    )
