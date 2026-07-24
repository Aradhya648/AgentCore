"""Debate orchestration SSE payload wire models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agentcore.runtime.events.payloads._base import WirePayload, absent


class EvidenceLedgerEntry(WirePayload):
    """场级证据台账条目（Citation ⊃ 台账字段 + 登记方 side_key）。

    案卷预登记（批 D2）可选来源锚：``dossier_path`` / ``origin_id`` / ``dossier_label``；
    旧 journal / 旧向量缺字段 → 前端忽略，零回归。
    """

    id: str  # #e1, #e2, …
    url: str = ""
    title: str = ""
    snippet: str = ""
    site: str = ""
    date: str = ""
    tier: str = "unknown"  # official | media | unknown | weak | blocked
    side_key: str = ""  # 登记方；主持人底料 = moderator；案卷预登记 = dossier
    # 案卷来源锚（additive）：工作区相对路径 / 幕1 #rN / 透镜人话标签。
    dossier_path: str = ""
    origin_id: str = ""
    dossier_label: str = ""


class DebateSideInfo(WirePayload):
    key: str
    name: str
    stance: str
    is_subject: bool
    model: str | None = absent(
        "Display-only model hint on some debate forms; absent on older wire."
    )


class DebateSpeechArgument(WirePayload):
    """辩手发言的一条结构化论点（后端 speech_parse 产出）。"""

    id: str
    title: str
    body: str


class DebateRoundSide(WirePayload):
    key: str
    name: str
    run_id: str
    ok: bool
    # 部分失败续赛时该方缺席（无立论）；跳过对其质询与对抗记分。缺字段（老事件）→ false。
    absent: bool = False
    # 结构化论点大纲；缺字段 / 空列表（老 journal）→ 前端启发式回退 parseSpeechArguments。
    arguments: list[DebateSpeechArgument] = Field(default_factory=list)
    # 轮内 beat；缺字段（老 journal / 正反）→ statement。
    beat: Literal["statement", "attack", "defense", "rebuttal", "thread", "crux"] = "statement"


class DebateFindingInfo(WirePayload):
    """红队 finding 结构载荷（O2：全文靠 run_id）。"""

    id: str
    severity: Literal["critical", "major", "minor"]
    target: str
    attacker_key: str
    status: Literal["open", "answered", "closed", "escalated", "deadlocked", "unanswered"]
    disposition: str = ""
    attack_run_id: str = ""
    response_run_id: str = ""
    rebuttal_run_id: str = ""
    merged_from: list[str] = Field(default_factory=list)


class DebateThreadTurnInfo(WirePayload):
    """圆桌线程 turn 结构载荷（O2：全文靠 run_id）。"""

    speaker: str
    reply_to: str = ""
    run_id: str
    ok: bool = True
    beat: Literal["thread", "crux"] = "thread"


class DebateConsensusMapItem(WirePayload):
    topic: str
    consensus: list[str] = Field(default_factory=list)
    divergences: list[str] = Field(default_factory=list)
    crux: str = ""


class DebateVerdict(WirePayload):
    real_clash: bool
    new_arguments: bool
    converged: bool
    stop_reason: str
    rationale: str


class DebateClash(WirePayload):
    from_key: str
    to_key: str
    point: str


class DebateUserInterjection(WirePayload):
    ask: str
    target_key: str
    answered: bool


class DebateCrossExamExchange(WirePayload):
    question: str
    answer: str


class DebateCrossExam(WirePayload):
    target: str
    questioner: str
    exchanges: list[DebateCrossExamExchange]
    answer_run_id: str


class DebateWitnessExam(WirePayload):
    """批 D1 · 证人答问（additive）：主持人点名幕1 透镜证人的事实性问答。"""

    witness_key: str
    lens_run_id: str
    seat_run_id: str = ""
    name: str
    origin_caption: str = ""
    exchanges: list[DebateCrossExamExchange] = Field(default_factory=list)
    answer_run_id: str = ""


class DebateWitnessSeat(WirePayload):
    """批 D1 · 本场证人席位花名册条目。"""

    key: str
    name: str
    lens_run_id: str
    seat_run_id: str
    lens_label: str = ""
    origin_caption: str = ""


class DebateClosing(WirePayload):
    key: str
    name: str
    run_id: str
    ok: bool


class DebateRoundScore(WirePayload):
    argument: int
    engagement: int
    evidence: int
    penalties: list[str]
    note: str
    total: int


class DebateRoundInfo(WirePayload):
    round_no: int
    focus: str
    summary: str
    verdict: DebateVerdict
    sides: list[DebateRoundSide]
    clashes: list[DebateClash]
    user_interjections: list[DebateUserInterjection] = Field(default_factory=list)
    cross_exam: list[DebateCrossExam] = Field(default_factory=list)
    # 批 D1 · 证人答问；缺字段（老事件）→ []。
    witness_exam: list[DebateWitnessExam] = Field(default_factory=list)
    scores: dict[str, DebateRoundScore] = Field(default_factory=dict)
    # 本轮新登记的证据台账增量（live 徽章可溯源）；缺字段（老事件）→ []。
    evidence_ledger_delta: list[EvidenceLedgerEntry] = Field(default_factory=list)
    # 红队 finding 台账（结构 only）；缺字段（老事件）→ []。
    findings: list[DebateFindingInfo] = Field(default_factory=list)
    # 圆桌线程 turn 序；缺字段（老事件）→ []。
    thread_turns: list[DebateThreadTurnInfo] = Field(default_factory=list)


class DebateNarrativeRound(WirePayload):
    round_no: int
    focus: str
    summary: str
    verdict: DebateVerdict | None
    sides: list[DebateRoundSide]
    clashes: list[DebateClash]
    cross_exam: list[DebateCrossExam]
    witness_exam: list[DebateWitnessExam] = Field(default_factory=list)
    findings: list[DebateFindingInfo] = Field(default_factory=list)
    thread_turns: list[DebateThreadTurnInfo] = Field(default_factory=list)


class DebateHandoffInfo(WirePayload):
    """交接清单条目：按解决路径分类（value / fact / question）。"""

    kind: Literal["value", "fact", "question"]
    text: str


class DebateBriefInfo(WirePayload):
    crux: str
    strongest_points: dict[str, str]
    # 退役：新场次恒空；旧载荷降级渲染仍可读。
    risk_severities: dict[str, str] = Field(default_factory=dict)
    findings: list[DebateFindingInfo] = Field(default_factory=list)
    gate: str = ""
    must_fix: list[str] = Field(default_factory=list)
    consensus_map: list[DebateConsensusMapItem] = Field(default_factory=list)
    handoffs: list[DebateHandoffInfo] = Field(default_factory=list)
    decisive: str = ""
    leaning: str
    confidence: str
    recommendation: str


class DebateResultPayload(WirePayload):
    execution_id: str
    moderator_run_id: str
    form: Literal["debate", "red_team", "roundtable"]
    motion: str
    stop_reason: str
    opening: str = ""
    narrative_first: bool
    sides: list[DebateSideInfo]
    rounds: list[DebateRoundInfo]
    closings: list[DebateClosing] = Field(default_factory=list)
    # 批 D1 · 证人席位花名册；缺字段（老事件）→ []。
    witnesses: list[DebateWitnessSeat] = Field(default_factory=list)
    brief: DebateBriefInfo
    # 全场证据台账（权威）；缺字段（老事件）→ []。不动 citations_event。
    evidence_ledger: list[EvidenceLedgerEntry] = Field(default_factory=list)
    # 圆桌子题轴；缺字段（老事件）→ []。
    subtopics: list[str] = Field(default_factory=list)


class DebateRoundStartedPayload(WirePayload):
    execution_id: str
    moderator_run_id: str
    round_no: int
    focus: str
    # 本场是否开启质询（与 cross_exam_enabled(config) 同源）。每轮开场重复声明同一场常量；
    # 缺字段（老事件）→ 前端回退「正在小结…」。optional+default 保持向后兼容。
    cross_exam_enabled: bool = False
    # 主持人开场白：仅首轮携带（后续轮空/缺省）。前端 sticky 取第一个非空，不被后续覆盖；
    # 收场 debate_result.opening 仍是权威。缺字段（老 journal）→ ""。
    opening: str = ""
    # 形态信号供 live 状态条；缺字段（老事件）→ 前端可回退 group 前缀推断。
    form: Literal["debate", "red_team", "roundtable"] | None = absent(
        "Form signal for live status; absent on older wire."
    )


class DebateRoundPayload(DebateRoundInfo):
    execution_id: str
    moderator_run_id: str


class DebatePretrialSideInfo(WirePayload):
    key: str
    name: str


class DebatePretrialTask(WirePayload):
    query: str
    purpose: str = ""


class DebatePretrialOrder(WirePayload):
    side_key: str
    tasks: list[DebatePretrialTask] = Field(default_factory=list)
    source: Literal["debater", "auto", "empty"] = "empty"


class DebatePretrialInvestigator(WirePayload):
    side_key: str
    run_id: str
    parent_run_id: str
    ok: bool
    task_query: str = ""


class DebatePretrialStartedPayload(WirePayload):
    execution_id: str
    moderator_run_id: str
    thorough: bool = True
    sides: list[DebatePretrialSideInfo] = Field(default_factory=list)
    skip_reason: Literal["fast", "dossier_sufficient"] | None = absent(
        "Set when pretrial is skipped immediately; absent when phase proceeds."
    )


class DebatePretrialOrdersPayload(WirePayload):
    execution_id: str
    moderator_run_id: str
    thorough: bool = True
    sides: list[DebatePretrialSideInfo] = Field(default_factory=list)
    orders: list[DebatePretrialOrder] = Field(default_factory=list)
    investigator_count_per_side: int = 0
    retrieval_budget_per_investigator: int = 0


class DebatePretrialProgressPayload(WirePayload):
    execution_id: str
    moderator_run_id: str
    side_key: str = ""
    investigator_run_id: str = ""
    parent_run_id: str = ""
    status: Literal["completed", "failed"] = "completed"
    evidence_ledger_count: int = 0


class DebatePretrialCompletedPayload(WirePayload):
    execution_id: str
    moderator_run_id: str
    thorough: bool = True
    sides: list[DebatePretrialSideInfo] = Field(default_factory=list)
    status: Literal["done", "skipped", "degraded"] = "done"
    skip_reason: Literal["fast", "dossier_sufficient"] | None = absent(
        "Present when status=skipped."
    )
    orders: list[DebatePretrialOrder] = Field(default_factory=list)
    investigators: list[DebatePretrialInvestigator] = Field(default_factory=list)
    fallback_self_search: bool = False
    evidence_ready: bool = False
    evidence_ledger_count: int = 0
    evidence_ledger_delta: list[EvidenceLedgerEntry] = Field(default_factory=list)
