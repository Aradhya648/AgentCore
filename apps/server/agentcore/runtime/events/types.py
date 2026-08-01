"""SSE event type definitions and the SSEEvent dataclass."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

# L3 团队浏览器 M1 直播通道状态（`browser_live_status`）——single source shared by the
# factory (browser.py) and the wire model (payloads/browser.py), kept here in the
# dependency-light types module so neither has to import the payloads package.
BrowserLiveState = Literal["started", "no_session", "session_closed"]


class EventType(StrEnum):
    MESSAGE_START = "message_start"
    CONTENT_DELTA = "content_delta"
    CONTENT_RESET = "content_reset"
    REASONING_DELTA = "reasoning_delta"
    TOOL_PROGRESS = "tool_progress"
    TOOL_USE_START = "tool_use_start"
    # 工具执行阶段进度（联网搜索前端展示优化）: a running tool reports a coarse EXECUTION phase
    # between tool_use_start and tool_use_end — distinct from TOOL_PROGRESS (which means the
    # LLM is still streaming the call's ARGUMENTS). web_search emits querying/queued/fallback
    # so the waiting UI shows a live, honest state instead of a dead spinner. Transport-only
    # liveliness (like TOOL_PROGRESS): never journaled, never in the process timeline / judge
    # state — a reloaded turn's tools are already done, so it only rides the live stream.
    TOOL_USE_PROGRESS = "tool_use_progress"
    TOOL_USE_END = "tool_use_end"
    MESSAGE_END = "message_end"
    ERROR = "error"
    TITLE_GENERATED = "title_generated"
    # CEO→用户「下一步推荐」(下一步推荐): 2-4 个可点选的快捷追问，回合收尾后由一次 World B
    # 窄任务生成、附到刚完成的助手消息下。与 title_generated 同属「回合后元信息」——不进
    # 判定态（ProjectedTurn），三端 fold 一律 no-op。持久化上是 DERIVED（处置见
    # events/disposition.py）：与孪生 title 一致回写 Message.followups 列，reload 重现 chips
    # （非 journal allow-list、故不进 turn_journal）。
    FOLLOWUPS_GENERATED = "followups_generated"
    # Soft empty state when followups mint failed (quota/auth/upstream/timeout) and there
    # are no chips — transport-only chrome; folds no-op; EPHEMERAL (reload loses soft hint).
    FOLLOWUPS_UNAVAILABLE = "followups_unavailable"
    TURN_SAVED = "turn_saved"
    CITATIONS = "citations"
    # 引用即出处：独立 turn 级台账通道（对称辩论 O1；不占 citations_event）。
    # DERIVED → Message.evidence_ledger；payload 可带 delta / entries + cited_ids（P2 投影权威）。
    EVIDENCE_LEDGER = "evidence_ledger"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    # 委派级授权: suspend before workers start — user grants medium-risk tools for
    # the whole delegation (grant_delegation) or keeps per-call approval (per_call).
    DELEGATION_AUTHORIZATION_REQUIRED = "delegation_authorization_required"
    DELEGATION_AUTHORIZATION_RESOLVED = "delegation_authorization_resolved"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    CHECKPOINT_RESOLVED = "checkpoint_resolved"
    QUESTION_POSTED = "question_posted"
    PLAN_REVIEW_REQUIRED = "plan_review_required"
    PLAN_REVIEW_RESOLVED = "plan_review_resolved"
    # 团队预审薄预览: first-wave gate before workers start (≠ 波间 plan_review).
    TEAM_PREVIEW_REQUIRED = "team_preview_required"
    TEAM_PREVIEW_RESOLVED = "team_preview_resolved"
    # 阶段推进卡（批 B）：幕 1 命题卡升级为可操作交互；跨回合耐久，不挂起幕 1。
    STAGE_CARD_REQUIRED = "stage_card_required"
    STAGE_CARD_RESOLVED = "stage_card_resolved"
    PLAN_REVISED = "plan_revised"
    WORKSPACE_OP_REQUIRED = "workspace_op_required"
    # AI 协作白板 (AI协作白板.md §六 M2): a transport-only client-tool request — the
    # server asks the bound desktop to apply structured board ops to the open whiteboard
    # canvas and report back. Like WORKSPACE_OP_REQUIRED it is NOT journaled (it is a
    # request/response exchange, not turn content), so it stays out of the journal sets.
    BOARD_OP_REQUIRED = "board_op_required"
    # AI 协作白板 (AI协作白板.md §九): transport-only client-tool request — the server asks the
    # bound desktop to rasterize a subset of board elements (手绘 / 截图) to a PNG and report it
    # back so the vision reader can read it. Like BOARD_OP_REQUIRED it is NOT journaled (a
    # request/response exchange, not turn content), so it stays out of the journal sets.
    BOARD_READ_REQUIRED = "board_read_required"
    # Desktop Client Tools: transport-only client-tool request — the server asks the
    # bound Electron app to show an OS notification and report back. NOT journaled.
    DESKTOP_NOTIFY_REQUIRED = "desktop_notify_required"
    # Host 第三能力面 P0: transport-only client-tool — desktop fulfils host_* ops
    # (ping / info / audio_devices / open_settings) via backfill. NOT journaled.
    HOST_OP_REQUIRED = "host_op_required"
    # 本机 MCP Client: transport-only client-tool — desktop stdio MCP list/call
    # via backfill (never cloud→127.0.0.1). NOT journaled.
    MCP_OP_REQUIRED = "mcp_op_required"
    HANDOFF_SNAPSHOT_DONE = "handoff_snapshot_done"
    HANDOFF_JOB_STARTED = "handoff_job_started"
    HANDOFF_APPLY_DONE = "handoff_apply_done"
    RUN_PLAN = "run_plan"
    # 跨回合同图追加：新回合声明「已往上方协作图追加 N 名成员」锚点（落追加回合 journal）；
    # 生长帧（run_plan/run_*）带 host_message_id 并续写宿主 turn_id journal。
    GRAPH_APPEND = "graph_append"
    RUN_STARTED = "run_started"
    RUN_CONTEXT = "run_context"
    RUN_OUTPUT_DELTA = "run_output_delta"
    RUN_OUTPUT_RESET = "run_output_reset"
    RUN_REASONING_DELTA = "run_reasoning_delta"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    # 跑一半改方向 / 整轮停止：单 run 被中断（与 run_failed 正交）。
    # reason=redirect → 用户「立即改此人」；reason=stop → 整轮 abort。
    RUN_CANCELLED = "run_cancelled"
    # 级联跳过 / graceful abort / 终端 cancel：未运行尾部物化为 SKIPPED（与 run_cancelled 正交）。
    # reason=cascade → on_failure=skip 波及下游；reason=abort → 整波 ABORT / plan_review stop /
    # 父 force_cancel·nested 中止·user_stop（ask_user soft_stop 续跑取消除外）。
    RUN_SKIPPED = "run_skipped"
    RUN_PROGRESS = "run_progress"
    RUN_TOOL_PROGRESS = "run_tool_progress"
    # Worker/run 活动相位（multi-agent fold 单一源）：等 LLM / 跑工具 / 等子团队 / 收尾。
    # EPHEMERAL liveliness（对称 run_tool_progress / coordination_wait）——reload 后由
    # status（pending/skipped/terminal）兜底；queued/skipped 不走本事件（见 status）。
    RUN_PHASE = "run_phase"
    BATCH_METRICS = "batch_metrics"
    RUN_ESCALATION = "run_escalation"
    # Worker 内部路由 Phase 1：Escalation Gate 方案层判定（确定性后置检查，正交于
    # 模型主动 escalate → run_escalation）。DERIVED：耐久记录仍走 ESCALATION_REQUIRED
    # / RunState.escalations；本事件是实时诊断信号。
    RUN_ESCALATION_GATE = "run_escalation_gate"
    ESCALATION_REQUIRED = "escalation_required"
    ESCALATION_RESOLVED = "escalation_resolved"
    # 团队便签墙 (§2.2 通): a worker pinned a short note (我定了 X / 提个醒 Y) to the batch
    # note wall for its concurrent siblings. Journaled (it rides a delegate turn alongside
    # RUN_PLAN, a surface type), so the team-notes panel replays on reload; folded onto the
    # ProjectedTurn so both ends render it (conformance-visible, unlike transport-only board ops).
    TEAM_NOTE_POSTED = "team_note_posted"
    # CEO 协调模式 Phase 1：多 worker 委派期间的确定性团队进展摘要（模板拼接，不调 LLM）。
    # DURABLE（P2）——落 journal；前端 fold 同 key 保最新，刷新后重建 StatusStrip 预览条。
    # → 见 docs/03-AI核心/编排器与CEO主Agent.md §协调模式（合成通道）
    TEAM_SYNTHESIS_PREVIEW = "team_synthesis_preview"
    # CEO 协调等待：captain 在 await_coordination_injection 空等团队事件期间推前端 UX。
    # EPHEMERAL——传输态心跳（进入 waiting=true / 退出 waiting=false；长等 ≤15s 刷新计数）；
    # 不落 journal（reload 时等待已结束或由 live SSE 重挂）。
    COORDINATION_WAIT = "coordination_wait"
    # 交付状态（能力闸门与交付诚实性）：delegate 批次收尾时把已有的完成度缺口 / artifacts
    # 对账 / degraded 信号汇成结构化交付对账（已交付文件 / 缺口 / 操作元数据），
    # 模板拼接、不调 LLM。DURABLE——落 journal；前端 fold 同 execution_id 保最新（反映
    # 最近一批委派的对账），供产物清单与 finish_guard；用户面无验收大卡（失败仅轻提示）。
    # 仅在有实质内容（有落盘文件或有缺口 / 行动项）时发射——纯 prose 成功批次保持无声。
    DELIVERY_STATUS = "delivery_status"
    # 协调中用户插话：POST …/messages 在 live CoordinationSession 时注入；status 同 key
    # 保最新（received → addressed / queued / failed）。DURABLE——team 块时间线重放徽标。
    USER_INTERJECTION = "user_interjection"
    # 同对话 FIFO 排队（D9 · 发送即有流）：in-flight 时 POST …/messages 立即在响应 SSE 上
    # 发射；队列 drain 启动该回合后**同一连接**续流。EPHEMERAL——传输态排队提示，不落 journal。
    TURN_QUEUED = "turn_queued"
    # 异步团队产出投递（批次 1）：执行与附着回合解耦后的一等状态。
    # DURABLE——落宿主 turn journal；前端 v1 静态「后台运行中」/完成后刷新（实时通道二期）。
    EXECUTION_DETACHED = "execution_detached"
    EXECUTION_COMPLETED = "execution_completed"
    DEBATE_RESULT = "debate_result"
    DEBATE_ROUND_STARTED = "debate_round_started"
    DEBATE_ROUND = "debate_round"
    # 庭前取证阶段（§二之二）：开赛后、首轮立论前；DURABLE 结构化 + 增量。
    DEBATE_PRETRIAL_STARTED = "debate_pretrial_started"
    DEBATE_PRETRIAL_ORDERS = "debate_pretrial_orders"
    DEBATE_PRETRIAL_PROGRESS = "debate_pretrial_progress"
    DEBATE_PRETRIAL_COMPLETED = "debate_pretrial_completed"
    # 提问确认交互统一：热路 pending 交互失效（假卡消灭）。payload={interaction_id, kind}。
    INTERACTION_ORPHANED = "interaction_orphaned"
    # BYOK soft gate (开放主流AI模型接入 §4.5): preflight hint when probe says the
    # user's model may lack tool calling. DURABLE（P2）——落 journal；runs 投影 → 横幅。
    TURN_WARNING = "turn_warning"
    # AI Town simulation (M1): tick lifecycle + agent snapshots. Persisted in sim_event,
    # not turn_journal — EPHEMERAL disposition (see disposition.py).
    SIM_TICK_STARTED = "sim.tick_started"
    SIM_TICK_ENDED = "sim.tick_ended"
    SIM_AGENT_ACTION = "sim.agent_action"
    SIM_AGENT_STATE = "sim.agent_state"
    SIM_INTERACTION = "sim.interaction"
    SIM_WORLD_EVENT = "sim.world_event"
    SIM_TICK_FRAME = "sim.tick_frame"
    # L3 团队浏览器 M1 直播 (内置浏览器与Agent浏览器提案.md · D13–D14): live screencast
    # frames + coarse status ride a per-conversation SSE bypass (GET …/browser/live), NOT the
    # turn journal. Both EPHEMERAL (disposition.py) — base64 jpeg frames + status never persist.
    BROWSER_LIVE_FRAME = "browser_live_frame"
    BROWSER_LIVE_STATUS = "browser_live_status"
    # AI 恋综 / 节目模式 overlays（录播生产 → AgentTown 节目壳）
    SIM_SHOW_HEART_PICK = "sim.show.heart_pick"
    SIM_SHOW_PAIR_FORMED = "sim.show.pair_formed"
    SIM_SHOW_AFFECTION_SHIFT = "sim.show.affection_shift"
    SIM_SHOW_ZERO_VOTE_ALERT = "sim.show.zero_vote_alert"
    SIM_SHOW_DEPARTURE = "sim.show.departure"
    SIM_SHOW_REVEAL = "sim.show.reveal"
    SIM_SHOW_EPISODE_GATE = "sim.show.episode_gate"


class FinishReason(StrEnum):
    END_TURN = "end_turn"
    MAX_ROUNDS = "max_rounds"
    DEGRADED = "degraded"
    UNPRODUCTIVE = "unproductive"
    ERROR = "error"
    CANCELLED = "cancelled"
    # Crash / lease-sweeper salvage of a mid-flight turn with no unfinished DAG to redrive
    # (流式回复持久化 §3.4): stream_state → incomplete + turn_end(interrupted).
    INTERRUPTED = "interrupted"
    # 挂起即收口 (②): the turn ended NOT because it finished, but because it hit a durable
    # checkpoint (ask_user blocking / plan_review) and finalized in place — its frame +
    # journal are persisted and it awaits ``POST .../resume``. Distinct from END_TURN (the
    # turn is NOT done) and CANCELLED (no error / no abort): the client renders the stream's
    # close as the single resume card.
    PAUSED = "paused"


@dataclass
class SSEEvent:
    """A single event to be sent over the SSE stream."""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    # Journal seq for DURABLE facts (SSE ``id:`` line). Set after the persist barrier
    # resolves — never part of the JSON envelope. EPHEMERAL / delta events leave this None.
    seq: int | None = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
