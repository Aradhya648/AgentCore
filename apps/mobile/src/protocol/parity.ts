// 对等对账门禁 (parity gate) · 登记表 —— 桌面/协议新增「该上手机」的交互面时，漏改手机 →
// 门禁自动响，而非悄悄漂回去 (cross-platform-frontend.mdc:「手机 = 桌面 − 物理做不到的能力」)。
//
// 三锚（数据在此，校验在 parity.check.ts，挂在现有 mobile conformance / CI job 上）：
//   锚 A · 协议事件（编译期响）：{@link EVENT_PARITY} 是 Record<SSEEventType, ParityEntry>。
//     SSEEventType 是后端单一源自动生成的穷尽联合 (eventTypes.generated.ts)、两端 fold 已
//     `assertNever` 它。再做成 Record → 后端加新事件、`pnpm gen:types` 重生成联合后，缺键即
//     `tsc` 失败（CI mobile typecheck 门禁），直到你给出手机对等裁决。与 fold 的 assertNever 同
//     款棘轮。
//   锚 B · 桌面交互面（测试期响）：{@link DESKTOP_CHAT_PARITY} 列举 apps/desktop/.../components/
//     chat 顶层 .tsx + `ask/` 子树（提问 intent 专用卡）的对等裁决；parity.check.ts 扫对照面、
//     断言每个 .tsx 都在表里有键（桌面新建一面 → conformance 失败直到分类）。捕获非事件通道喂
//     的面（如 ③ 记忆卡走 REST、后台任务卡、@提及…）。其余 chat 子目录（debate/…）仍不入表免抖动。
//   锚 C · 桌面页面（测试期响）：{@link DESKTOP_PAGE_PARITY} 列举 apps/desktop/.../pages 下每个
//     .tsx 页面（含子目录）的对等裁决；parity.check.ts 递归扫该目录、断言每个 .tsx 都在表里有键
//     （桌面新建一页 → conformance 失败直到分类）。接住整页 / route 级漂移（白板/工具箱/手册/成员…）。
//
// 边界（诚实）：门禁强制的是「有没有给出对等裁决」，不验证手机实现是否正确/已接线——那是
// typecheck（死/没接线代码）、conformance（fold 漂移）、可视化自检的活。三层分层互补，本表只补
// 「整面漏掉/没分类」这一段。符合 protocol-conformance.mdc「组件/chrome 不进巡检」：此处不巡检
// 实现，只强制一条裁决记录存在，两端 chrome 仍自由分叉。

import type { SSEEventType } from "@agentcore/contract-types";

/** 一条对等裁决。
 *  - `ported`：手机已覆盖（`surface` 给出手机落点：组件/位置）。
 *  - `simplified`：已知缺口 / 有意精简（`reason` 说明精简了什么/为何；门禁仍绿，报告会列出）。
 *  - `impossible`：手机物理做不到（`reason` 说明绑了哪种本地/桌面专属能力）。
 *  - `internal`：非用户面（纯协议管线/派生/渲染叶，`reason` 一句点明）。 */
export type ParityVerdict = "ported" | "simplified" | "impossible" | "internal";

export interface ParityEntry {
  verdict: ParityVerdict;
  /** 手机落点（ported 必填；simplified 视情可填）：组件名或位置。 */
  surface?: string;
  /** 理由（simplified / impossible / internal 必填；ported 可省，surface 已自证）。 */
  reason?: string;
}

/** 锚 A · 协议事件 → 手机对等裁决。`Record<SSEEventType, …>` 强制穷尽：缺键 = tsc 失败。 */
export const EVENT_PARITY: Record<SSEEventType, ParityEntry> = {
  // —— CEO 内联时间线：正文 / 思考 / 工具 / 引用 ——
  content_delta: { verdict: "ported", surface: "AssistantView 时间线 · 正文" },
  content_reset: {
    verdict: "ported",
    surface: "fold · 清正文（仅 reason=finish_guard 折 rework chip）",
  },
  reasoning_delta: { verdict: "ported", surface: "AssistantView · 思考块" },
  tool_use_start: {
    verdict: "ported",
    surface:
      "AssistantView · 工具步 (CEO 自身调用) + RunDetail · 队员工具明细 (run_id 侧，extractRunToolCalls)",
  },
  tool_use_end: {
    verdict: "ported",
    surface:
      "AssistantView · 工具步 (CEO 自身调用) + RunDetail · 队员工具明细 (run_id 侧，extractRunToolCalls)",
  },
  tool_use_progress: {
    verdict: "ported",
    surface:
      "AssistantView · 工具步执行阶段 (CEO, extractToolPhases) + TeamView · 队员节点 (worker run_id, extractWorkerToolPhases)",
  },
  citations: { verdict: "ported", surface: "AssistantView · 来源" },
  evidence_ledger: {
    verdict: "ported",
    surface:
      "fold → ProjectedTurn.evidenceLedger → ChatPage/Preview Markdown；history=toMessageDetail(evidence_ledger)；辩论 `#eN` 仍走 extractEvidenceLedger→TeamView（O7 无 Popover）",
  },

  // —— 多 Agent 团队 ——
  run_plan: { verdict: "ported", surface: "TeamView" },
  graph_append: {
    verdict: "ported",
    surface:
      "AssistantView · 跨回合同图追加锚点（fold → process.graph_append；宿主图仍 TeamView）",
  },
  coordination_wait: {
    verdict: "internal",
    reason: "协调等待实时信号；手机 fold no-op，等待态由 run/status 派生呈现",
  },
  run_started: { verdict: "ported", surface: "TeamView" },
  run_phase: {
    verdict: "ported",
    surface:
      "TeamView · worker 活动相位（thinking/tool/waiting_children/winding_down；queued=pending；skipped=status）",
  },
  run_context: {
    verdict: "ported",
    surface:
      "AssistantView · 收到的上下文 (CEO 侧 captainContext) + RunDetail · 队员收到的上下文 (worker 侧 receivedContext)",
  },
  run_output_delta: {
    verdict: "ported",
    surface: "TeamView · 队员输出预览 + RunDetail · 输出全文",
  },
  run_output_reset: {
    verdict: "ported",
    surface: "fold · 清 worker 草稿（仅 reason=finish_guard 折 rework 步）",
  },
  run_reasoning_delta: {
    verdict: "ported",
    surface: "RunDetail · 队员思考全文",
  },
  run_tool_progress: { verdict: "ported", surface: "TeamView · 队员工具进度" },
  run_completed: {
    verdict: "ported",
    surface: "TeamView + RunDetail (交接简报 / 资源用量 / 时长 / 关系)",
  },
  run_failed: { verdict: "ported", surface: "TeamView" },
  run_cancelled: {
    verdict: "ported",
    surface: "TeamView · 跑一半改方向 / 整轮停止",
  },
  run_skipped: {
    verdict: "ported",
    surface: "TeamView · 未执行（级联跳过 / graceful abort）",
  },
  run_progress: {
    verdict: "internal",
    reason: "进度由 run 状态派生（仅时间线计数标记），无独立面",
  },
  plan_revised: { verdict: "ported", surface: "TeamView · 计划已调整 痕迹" },
  run_escalation: {
    verdict: "ported",
    surface: "AssistantView · escalation 时间线标记 (非阻塞轻行)",
  },
  run_escalation_gate: {
    verdict: "internal",
    reason:
      "Escalation Gate 判定实时信号；耐久升级仍走 escalate / RunState.escalations",
  },
  escalation_required: {
    verdict: "ported",
    surface: "AssistantView · EscalationAnswer 待你拍板卡 (②)",
  },
  escalation_resolved: {
    verdict: "ported",
    surface: "AssistantView · 升级收束轻行",
  },

  // —— 辩论 ——
  debate_result: { verdict: "ported", surface: "DebateView" },
  debate_round_started: { verdict: "ported", surface: "LiveDebateNarrative" },
  debate_round: {
    verdict: "ported",
    surface: "LiveDebateNarrative / DebateView",
  },
  debate_pretrial_started: {
    verdict: "ported",
    surface: "LiveDebateNarrative · 庭前取证",
  },
  debate_pretrial_orders: {
    verdict: "ported",
    surface: "LiveDebateNarrative · 庭前取证",
  },
  debate_pretrial_progress: {
    verdict: "ported",
    surface: "LiveDebateNarrative · 庭前取证",
  },
  debate_pretrial_completed: {
    verdict: "ported",
    surface: "LiveDebateNarrative · 庭前取证 / DebateView",
  },

  // —— 团队便签墙 ——
  team_note_posted: { verdict: "ported", surface: "TeamView · 团队便签" },
  team_synthesis_preview: {
    verdict: "ported",
    surface: "TeamView · 协调进展预览（fold 对齐 StatusStrip）",
  },
  delivery_status: {
    verdict: "ported",
    surface:
      "TeamView · 交付轻提示（partial/blocked 一句；delivered/notes 静默；对齐桌面 DeliveryStatusMount）",
  },
  user_interjection: {
    verdict: "ported",
    surface:
      "ChatPage · InterjectionBubbles 主时间线用户气泡 + 四态文案（fold → userInterjections）",
  },
  turn_queued: {
    verdict: "ported",
    surface: "ChatPage · 排队等待条（extractTurnQueued）",
  },
  execution_detached: {
    verdict: "internal",
    reason: "异步团队转后台：v1 fold no-op；UI 呈现另行委派",
  },
  execution_completed: {
    verdict: "ported",
    surface: "ChatPage · getMessages 短延迟刷新拉入 harvest 终稿",
    reason:
      "fold no-op；live SSE 路径触发消息窗刷新（对齐桌面 refreshAfterExecutionCompleted）",
  },

  // —— 阻塞交互（审批热路径 PauseCard；冷恢复 ResumeCard）——
  approval_required: { verdict: "ported", surface: "PauseCard" },
  approval_resolved: { verdict: "ported", surface: "PauseCard" },
  interaction_orphaned: {
    verdict: "ported",
    surface: "静默撤卡（无 OrphanedInteractionCard 墓碑）",
    reason:
      "定案 A：不可操作交互静默消失；store/fold 仍记 orphaned，UI 不渲染灰态卡",
  },
  delegation_authorization_required: {
    verdict: "ported",
    surface: "DelegationAuthorizationCard",
  },
  delegation_authorization_resolved: {
    verdict: "ported",
    surface: "DelegationAuthorizationCard",
  },
  checkpoint_required: {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "协议折入 ResumeCard 可恢复；桌面 CheckpointCard：kickoff/decision 共用 AskDecisionBody，proposal_pick/risk_ack/organize_plan 专用体；daily_review 勾选墙已对等进 ResumeCard；其余 intent 精简承接（见 DESKTOP_CHAT_PARITY · CheckpointCard / ask/*）",
  },
  checkpoint_resolved: {
    verdict: "simplified",
    surface: "ResumeCard",
    reason: "同上 · 冷路径痕迹；PauseCard 仅审批热路径，不承接 checkpoint",
  },
  plan_review_required: { verdict: "ported", surface: "ResumeCard" },
  plan_review_resolved: { verdict: "ported", surface: "ResumeCard" },
  team_preview_required: { verdict: "ported", surface: "ResumeCard" },
  team_preview_resolved: { verdict: "ported", surface: "ResumeCard" },
  stage_card_required: { verdict: "ported", surface: "StageCard" },
  stage_card_resolved: { verdict: "ported", surface: "StageCard" },

  // —— 非阻塞提问 (①) ——
  question_posted: { verdict: "ported", surface: "NonBlockingAskCard (①)" },

  // —— 跟进推荐 ——
  followups_generated: {
    verdict: "ported",
    surface: "ChatPage · 下一步 chips",
  },
  followups_unavailable: {
    verdict: "ported",
    surface: "ChatPage · 跟进不可用标记（fold / stopLifecycle）",
  },

  // —— 收尾 / 错误 ——
  error: { verdict: "ported", surface: "ChatPage · 错误条" },
  message_start: {
    verdict: "internal",
    reason:
      "服务端 message_id 开泡；fold 清正文/process 并保留同 execution 的 runs/agents（跨回合同图追加）",
  },
  message_end: { verdict: "ported", surface: "ChatPage · 收尾 + 回合总账" },

  // —— 纯管线 / 派生（非用户面）——
  turn_warning: { verdict: "ported", surface: "ChatPage · 预检警告条" },
  turn_saved: { verdict: "internal", reason: "落库标记，无 UI" },
  title_generated: {
    verdict: "internal",
    reason: "标题经 REST/会话列表呈现，非回合流面",
  },
  tool_progress: {
    verdict: "internal",
    reason: "粗粒度旧进度事件，fold no-op",
  },

  // —— 诊断（桌面 power-user 面）——
  batch_metrics: {
    verdict: "simplified",
    reason: "调度埋点量化仅桌面诊断模式面板；手机无诊断面板 (fold no-op)",
  },

  // —— L3 团队浏览器直播（桌面工作区直播面板 + 接管，手机暂不做）——
  browser_live_frame: {
    verdict: "simplified",
    reason:
      "L3 团队浏览器直播帧（base64 jpeg 截屏，ephemeral 侧信道、从不落 turn journal）喂桌面工作区直播面板；手机暂不做直播/接管面 (fold no-op)",
  },
  browser_live_status: {
    verdict: "simplified",
    reason:
      "同上 · 直播通道状态（started / no_session / session_closed）；手机无直播面板 (fold no-op)",
  },

  // —— AI 协作白板（桌面画布面，手机无板）——
  board_op_required: {
    verdict: "impossible",
    reason: "AI 协作白板为桌面画布面，手机无板 (fold no-op)",
  },
  board_read_required: {
    verdict: "impossible",
    reason: "同上 · 读板为桌面画布面",
  },
  desktop_notify_required: {
    verdict: "impossible",
    reason: "桌面 OS 通知为 Electron Client Tool，手机无此通道 (fold no-op)",
  },
  host_op_required: {
    verdict: "impossible",
    reason: "本机 Host 回填为 Electron Client Tool，手机无此通道 (fold no-op)",
  },
  mcp_op_required: {
    verdict: "impossible",
    reason:
      "本机 MCP stdio 回填为 Electron Client Tool，手机无此通道 (fold no-op)",
  },

  // —— 草稿工作区（本地文件夹）/ 本地↔云交接（物理做不到）——
  workspace_op_required: {
    verdict: "impossible",
    reason: "工作区操作绑本地文件夹；纯云瘦客户端无本地侧",
  },
  handoff_snapshot_done: {
    verdict: "impossible",
    reason: "本地↔云交接（后台任务桥）的本地侧，手机无本地",
  },
  handoff_job_started: {
    verdict: "impossible",
    reason: "同上 · 后台任务桥本地侧",
  },
  handoff_apply_done: {
    verdict: "impossible",
    reason: "同上 · 把云端改动合并回本地磁盘，手机无本地",
  },

  // —— AI 小镇模拟（桌面 MVP，手机无模拟面）——
  "sim.agent_action": {
    verdict: "impossible",
    reason: "AI 小镇模拟仅桌面 MVP，手机无模拟面 (fold no-op)",
  },
  "sim.agent_state": {
    verdict: "impossible",
    reason: "同上 · 居民状态同步",
  },
  "sim.interaction": {
    verdict: "impossible",
    reason: "同上 · 居民交互气泡/交易",
  },
  "sim.tick_started": {
    verdict: "impossible",
    reason: "同上 · 模拟 tick 开始",
  },
  "sim.tick_ended": {
    verdict: "impossible",
    reason: "同上 · 模拟 tick 结束",
  },
  "sim.tick_frame": {
    verdict: "impossible",
    reason: "同上 · 模拟 tick 帧快照",
  },
  "sim.world_event": {
    verdict: "impossible",
    reason: "同上 · 世界事件",
  },
  "sim.show.affection_shift": {
    verdict: "impossible",
    reason: "AI 恋综观测仅桌面/Unity 客户端，手机无模拟面 (fold no-op)",
  },
  "sim.show.departure": {
    verdict: "impossible",
    reason: "同上 · 零票离场",
  },
  "sim.show.episode_gate": {
    verdict: "impossible",
    reason: "同上 · 期节点门",
  },
  "sim.show.heart_pick": {
    verdict: "impossible",
    reason: "同上 · 心动投票",
  },
  "sim.show.pair_formed": {
    verdict: "impossible",
    reason: "同上 · 互选配对",
  },
  "sim.show.reveal": {
    verdict: "impossible",
    reason: "同上 · 公布环节",
  },
  "sim.show.zero_vote_alert": {
    verdict: "impossible",
    reason: "同上 · 零票预警",
  },
};

/** 锚 B · 桌面交互面（apps/desktop/.../components/chat 顶层 .tsx + `ask/` 子树）→ 手机对等裁决。
 *  key = 组件相对 chat 根的路径（正斜杠、去扩展名；顶层无前缀，ask 子树为 `ask/…`）。
 *  parity.check.ts 扫对照面断言每个 .tsx 都在此有键，并报告指向已不存在文件的陈旧键。
 *  infra / 渲染叶子记 `internal`（仍要求一句 reason，强制是有意分类而非遗漏）。 */
export const DESKTOP_CHAT_PARITY: Record<string, ParityEntry> = {
  // —— 互动卡：已上手机 ——
  NonBlockingAskCard: { verdict: "ported", surface: "NonBlockingAskCard (①)" },
  EscalationCard: {
    verdict: "ported",
    surface: "AssistantView · EscalationAnswer (②)",
  },
  MemoryUpdateCard: { verdict: "ported", surface: "MemoryUpdateCard (③)" },
  CheckpointCard: {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "桌面 kickoff/decision 共用 AskDecisionBody；proposal_pick/risk_ack/organize_plan 专用体；daily_review 勾选墙已对等进 ResumeCard；手机其余 intent 仍精简 ResumeCard 承接（organize_plan 仍确认=全保留）",
  },
  PlanReviewCard: { verdict: "ported", surface: "ResumeCard" },
  TeamPreviewCard: { verdict: "ported", surface: "ResumeCard" },
  PendingDecisionMarker: {
    verdict: "internal",
    reason:
      "桌面 pending 交互行内单行标记；手机 PauseCard/ResumeCard 自带等价态",
  },
  ApprovalPrompt: { verdict: "ported", surface: "PauseCard" },
  HotDecisionTrace: {
    verdict: "ported",
    surface: "AssistantView · hot-trace 轻状态行（resolved 门控，D3）",
  },
  ResumePrompt: {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "桌面 ResumePrompt 复用 CheckpointCard 全 intent UI；手机精简 ResumeCard 降级承接（与 CheckpointCard 同缺口）",
  },
  FileArtifactsCard: { verdict: "ported", surface: "FileArtifactsCard" },
  TurnFileChangesReview: {
    verdict: "simplified",
    surface: "FileArtifactsCard",
    reason:
      "桌面 A1/A1+/A2′「查看改动」+ 回退基线（云 files/diff / 本机 sidecar）；手机产物卡仅清单+深链文件页，本期不做基线 diff/回退面（代码基本功 A+B 定案验收落桌面）",
  },
  FollowupChips: { verdict: "ported", surface: "ChatPage · 下一步 chips" },
  StageCard: { verdict: "ported", surface: "StageCard" },
  StageCardDock: {
    verdict: "ported",
    surface: "StageCard mounted in ChatPage",
  },
  ConversationOutline: {
    verdict: "simplified",
    reason: "对话大纲/回合导航，手机暂不做（小屏以滚动代）",
  },
  FindBar: {
    verdict: "simplified",
    reason: "会话内查找，手机暂不做（无 Cmd+F 快捷键）",
  },
  ReceivedContext: {
    verdict: "ported",
    surface: "AssistantView · 收到的上下文",
  },
  TeamNotesPanel: { verdict: "ported", surface: "TeamView · 团队便签" },
  UserInterjectionsPanel: {
    verdict: "ported",
    surface:
      "ChatPage · InterjectionBubbles（团队块内追溯；主叙事见 InterjectionTimeline）",
  },
  InterjectionTimeline: {
    verdict: "ported",
    surface:
      "ChatPage · InterjectionBubbles（主时间线用户气泡 + 四态文案；对齐桌面）",
  },
  SourceCards: { verdict: "ported", surface: "AssistantView · 来源" },
  CitationTierBadge: {
    verdict: "ported",
    surface: "AssistantView · 来源可信度徽标",
  },
  StatusStrip: { verdict: "ported", surface: "ChatPage · 状态 meta 行" },
  DebateProgressLine: {
    verdict: "ported",
    surface: "TeamView · 辩论进展预览（fold 对齐 StatusStrip）",
  },
  TeamSynthesisPreviewLine: {
    verdict: "ported",
    surface: "TeamView · 协调进展预览（fold 对齐 StatusStrip）",
  },
  StreamingIndicator: {
    verdict: "ported",
    surface: "ChatPage · 流式状态条",
  },
  TurnWarningBanner: {
    verdict: "ported",
    surface: "ChatPage · 预检警告条",
  },
  ParallelTimeline: {
    verdict: "ported",
    surface: "AssistantView · ProcessTimeline",
  },
  GraphAppendAnchor: {
    verdict: "simplified",
    reason:
      "桌面跨回合同图追加锚点条（滚回宿主协作图）；手机 TeamView 无跨气泡图追加跳转，追加回合仍走常规进程时间线",
  },

  // —— 提问 intent 专用卡（ask/；桌面 CheckpointCard 分支出；手机本期降级 ResumeCard）——
  "ask/AskDecisionBody": {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "通用澄清卡（decision + wire kickoff）：AskCardShell + 行式选项；手机无专用卡，ResumeCard 精简承接",
  },
  "ask/AskCommenceKickoff": {
    verdict: "internal",
    reason:
      "已退役 kickoff V2 Brief+Choose；仅离线预览对照，生产走 AskDecisionBody",
  },
  "ask/ProposalPickBody": {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "proposal_pick 生产卡：AskCardShell + 行式单选；手机无专用卡，ResumeCard chips 降级承接",
  },
  "ask/RiskAckBody": {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "risk_ack 生产卡：AskCardShell + 行式多选；手机无专用卡，ResumeCard chips 降级承接",
  },
  "ask/OrganizePlanBody": {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "organize_plan 生产卡：AskCardShell + 行式多选；手机无勾选墙，ResumeCard 确认=全保留降级",
  },
  "ask/DailyReviewBody": {
    verdict: "ported",
    surface:
      "ResumeCard · daily_review 勾选墙（默认全选 / 取消=跳过 / selected 语义对齐）",
  },
  "ask/AskUserFields": {
    verdict: "simplified",
    surface: "ResumeCard",
    reason:
      "桌面结构化问答内核（choice/text/其他逃逸 + useAskAnswer）；手机 ResumeCard 内嵌精简问答，无对等 AskUserFields 面",
  },
  "ask/AskCardShell": {
    verdict: "internal",
    reason:
      "ask intent 共用卡壳（头/体/底）；kickoff/decision 同壳，非独立对等面",
  },
  "ask/AskOptionRow": {
    verdict: "internal",
    reason: "ask 行式选项组（AskRowGroup），非独立对等面",
  },
  "ask/AskCommenceParts": {
    verdict: "internal",
    reason:
      "kickoff 预览/退役路径共享 chrome（OptionButton 等）；生产行式卡不再依赖",
  },
  "ask/preview/AskCommenceShared": {
    verdict: "internal",
    reason: "ask commence 离线预览共享叶（开发自检），非用户产品面",
  },
  "ask/preview/AskCommenceV1": {
    verdict: "internal",
    reason: "ask commence 离线预览变体（开发自检），非用户产品面",
  },
  "ask/preview/AskCommenceV2": {
    verdict: "internal",
    reason: "ask commence 离线预览变体（退役 V2 对照），非用户产品面",
  },
  "ask/preview/AskCommenceV3": {
    verdict: "internal",
    reason: "ask commence 离线预览变体（开发自检），非用户产品面",
  },
  "ask/preview/AskCommenceV4": {
    verdict: "internal",
    reason: "ask commence 离线预览变体（开发自检），非用户产品面",
  },
  "ask/preview/AskCommenceV5": {
    verdict: "internal",
    reason:
      "ask commence 离线预览：挂载生产 AskDecisionBody（通用澄清），非独立产品面",
  },

  // —— 有意精简 ——
  InlineTeamGraph: {
    verdict: "simplified",
    reason:
      "手机用竖排 TeamView 代 React-Flow 画布；点队员卡下钻 RunDetail 详情面（对齐桌面抽屉信息，小屏合理）",
  },
  MentionMenu: {
    verdict: "simplified",
    reason: "手机 composer 不带 @ 提及菜单 (niche)",
  },
  RetryBanner: {
    verdict: "ported",
    surface: "ChatPage · 错误条（去配置 / 重连）",
  },
  SourcePreview: {
    verdict: "simplified",
    reason: "手机来源为纯链接，无悬浮预览（桌面 affordance）",
  },
  ReadUrlSourceCollection: {
    verdict: "simplified",
    reason:
      "桌面把 ≥2 条连续 read_url 工具步合并为来源集合（SourceCards 式 favicon pill 行 / 展开来源列表）；手机 AssistantView 工具步逐条呈现 read_url（tool_use_end 已 ported），未做该桌面渲染层聚合",
  },
  BrowserActivityCard: {
    verdict: "simplified",
    reason:
      "L3 团队浏览器 M0：桌面把 worker browser_* 步聚合成关键帧活动卡（BrowserActivityCard / 单步 BrowserResult + 懒取工作区关键帧）；手机按 D12 退化为文本工具行（tool_use_end 已 ported、display 照折不丢数据），富卡后置",
  },
  BrowserTakeoverCard: {
    verdict: "simplified",
    reason:
      "L3 团队浏览器 M2 接管留档卡（桌面直播面板发起接管后的只读时间线痕迹，起止 DURABLE 标记走 REST/store，接管期零帧落盘）；手机暂不做直播/接管面，痕迹卡随该功能后置",
  },
  PermissionChangeLine: {
    verdict: "simplified",
    reason:
      "桌面把会话级权限轴切换（PUT permission-axes → 审计 permission.axes_changed，走 REST 非事件通道）在对话流内渲染「权限 A → B」系统提示行；手机可在 AutonomySettings 切档，但暂不在对话流内渲染该切换提示行（parity 最小同步，随需后置）",
  },
  ConversationHydrateOverlay: {
    verdict: "simplified",
    reason:
      "桌面冷加载/hydrate 失败全屏诚实壳（防空草稿可发送）；手机 ChatPage 用自身 loading/error 态承接，不做同构全屏 overlay",
  },

  // —— 物理做不到 ——
  BackgroundTaskCard: {
    verdict: "impossible",
    reason: "本地↔云后台任务桥，手机无本地侧 (④)",
  },
  BackgroundTaskReview: {
    verdict: "impossible",
    reason: "同上 · 评审并把云端改动合并回本地磁盘",
  },
  DraftWorkspaceAssignPrompt: {
    verdict: "impossible",
    reason: "指派本地工作区，手机无本地",
  },
  RunConfirmPrompt: {
    verdict: "impossible",
    reason: "用户直触 bash 的本地运行确认卡（fsApi 本会话放行），手机无本地侧",
  },
  DelegationAuthorizationCard: {
    verdict: "ported",
    surface: "DelegationAuthorizationCard",
  },

  // —— infra / 渲染叶子（非交互-对等面）——
  ChatView: { verdict: "internal", reason: "对话容器" },
  ConversationDecisionPrompts: {
    verdict: "internal",
    reason:
      "决策卡单挂载容器（提问确认统一重构 P2：Chat/画布互斥复用同一实例），本身无 UI",
  },
  ConversationRoute: { verdict: "internal", reason: "路由壳" },
  MessageList: { verdict: "internal", reason: "消息列表容器" },
  MessageBubble: { verdict: "internal", reason: "气泡容器" },
  MessageInput: { verdict: "internal", reason: "composer 输入" },
  ToolLine: {
    verdict: "internal",
    reason: "工具行渲染叶（手机自有 ToolStep）",
  },
  Markdown: { verdict: "internal", reason: "共享渲染叶" },
  CodeBlock: { verdict: "internal", reason: "代码块渲染叶" },
  Diagram: { verdict: "internal", reason: "mermaid 渲染叶" },
  Favicon: { verdict: "internal", reason: "站点图标叶" },
  EvidenceBadge: {
    verdict: "ported",
    surface:
      "RunDetail · 输出（辩手发言全文）—— 手机独立 remarkEvidence 把【已核实·出处】/【待核实·推断】渲成 EvidenceBadge 徽章；`#eN` 台账解析 + 溯源底栏（含案卷路径/幕1 #rN，可跳转对话文件页）与桌面同构（批 D2）",
  },
  EvidenceLedgerContext: {
    verdict: "ported",
    surface:
      "EvidenceLedgerContext（手机自有）—— 场级台账 map 注入徽章解析 `#eN`；溯源 Popover 桌面先行",
  },
  // 引用即出处 P1：回合调研台账通道 fold 进 ProjectedTurn.evidenceLedger / citedIds；
  // Citation.id 透传。来源卡 id 溯源完整面板桌面先行（对齐 O7）。
};

/** 锚 C · 桌面页面（apps/desktop/src/renderer/pages 下每个 .tsx，含子目录）→ 手机对等裁决。
 *  key = 相对 pages 根的路径（正斜杠、去 .tsx），子目录区分同名页（桶文件 ConversationsPage vs
 *  实体 conversations/ConversationsPage）。parity.check.ts 递归扫该目录断言每个 .tsx 都有键、并报
 *  陈旧键。接住整页 / route 级漂移：桌面新增一页 → conformance 失败直到给出手机对等裁决。 */
export const DESKTOP_PAGE_PARITY: Record<string, ParityEntry> = {
  // —— 已上手机（路由对齐）——
  ConversationPage: { verdict: "ported", surface: "ChatPage（对话）" },
  "conversations/ConversationsPage": {
    verdict: "ported",
    surface: "ChatPage · 会话列表（抽屉）",
  },
  MorePage: { verdict: "ported", surface: "MorePage（设置中心）" },
  OnboardingPreviewPage: {
    verdict: "simplified",
    reason: "桌面 #/preview 离线 onboarding 场景页；手机无对等预览路由",
  },
  LoginPage: { verdict: "ported", surface: "LoginPage" },
  FilesPage: { verdict: "ported", surface: "FilesPage / WorkspacesPage" },
  MessagesPage: { verdict: "ported", surface: "MessagesPage（IM）+ im/*" },
  ServiceUnavailablePage: {
    verdict: "ported",
    surface: "ServiceUnavailablePage",
  },
  "more/UsageSettings": { verdict: "ported", surface: "more/UsageSettings" },
  "more/ModelSettings": { verdict: "ported", surface: "more/ModelSettings" },
  "more/MoreIndexRedirect": {
    verdict: "simplified",
    reason: "桌面 /more 入口按 billing/服务商分流；手机 more 直达模型页",
  },
  "more/ProviderSettings": {
    verdict: "ported",
    surface: "more/ModelSettings · ProviderForm（手机合页）",
  },
  "more/AboutSettings": { verdict: "ported", surface: "more/AboutSettings" },
  "more/AccountSettings": {
    verdict: "ported",
    surface: "more/AccountSettings",
  },
  "more/ImPrivacySettings": {
    verdict: "ported",
    surface: "MessagesPage · 消息隐私（IM 设置）",
  },
  "more/FeedbackSettings": {
    verdict: "simplified",
    reason: "反馈设置页，手机暂不做",
  },
  "more/RedirectToOfficialChat": {
    verdict: "simplified",
    reason:
      "桌面旧 #/more/notices 跳转 IM 官方号；手机公告走消息页官方会话（无独立公告设置页）",
  },
  "more/LoginSessionsSection": {
    verdict: "ported",
    surface: "more/AccountSettings · 登录会话（sessionDisplay 同源裁决）",
  },

  // —— 有意精简 / 保持不做（⑥ 精简陪伴定位 & 明确决策）——
  ToolboxPage: { verdict: "simplified", reason: "工具箱保持不做（⑥）" },
  "toolbox/automations/AutomationsPage": {
    verdict: "simplified",
    reason:
      "站立任务 / 自动化收件箱仅桌面（云工作区定时·Webhook）；手机本波有意不接",
  },
  "toolbox/automations/InboxPanel": {
    verdict: "simplified",
    reason: "同上 · 站立任务收件箱仅桌面",
  },
  "toolbox/automations/StandingTaskEditor": {
    verdict: "simplified",
    reason: "同上 · 站立任务编辑仅桌面",
  },
  "toolbox/automations/StandingTasksPanel": {
    verdict: "simplified",
    reason: "同上 · 站立任务列表仅桌面",
  },
  "toolbox/workflows/WorkflowsPage": {
    verdict: "simplified",
    reason: "用户工作流画布/CRUD/直跑仅桌面；手机本波有意不接",
  },
  "toolbox/workflows/WorkflowEditorPage": {
    verdict: "simplified",
    reason: "同上 · 工作流编辑仅桌面",
  },
  "toolbox/workflows/WorkflowCanvas": {
    verdict: "simplified",
    reason: "同上 · 工作流画布仅桌面",
  },
  "toolbox/workflows/WorkflowNodeInspector": {
    verdict: "simplified",
    reason: "同上 · 节点检查器仅桌面",
  },
  "toolbox/workflows/workflowNodes": {
    verdict: "simplified",
    reason: "同上 · 画布节点叶仅桌面",
  },
  "toolbox/workflows/UseTemplateDialog": {
    verdict: "simplified",
    reason: "同上 · 从官方模板复制仅桌面",
  },
  "toolbox/workflows/RunWorkflowDialog": {
    verdict: "simplified",
    reason: "同上 · 工作流直跑对话框仅桌面",
  },
  "toolbox/ConnectorsPage": {
    verdict: "impossible",
    reason: "本机 MCP stdio 连接器仅 Electron；手机无本机 MCP Client",
  },
  "toolbox/ToolsPage": {
    verdict: "simplified",
    reason: "工具创作保持不做（⑥）",
  },
  "toolbox/GuidelinesPage": {
    verdict: "simplified",
    reason: "工具箱·指南保持不做（⑥）",
  },
  "toolbox/manual/ManualShell": {
    verdict: "simplified",
    reason: "产品手册归工具箱保持不做（本轮决策）",
  },
  "toolbox/manual/ManualIntro": {
    verdict: "simplified",
    reason: "产品手册保持不做（本轮决策）",
  },
  "toolbox/manual/ManualMechanism": {
    verdict: "simplified",
    reason: "产品手册保持不做（本轮决策）",
  },
  "toolbox/manual/ManualCollaboration": {
    verdict: "simplified",
    reason: "产品手册保持不做（本轮决策）",
  },
  "toolbox/manual/ManualReference": {
    verdict: "simplified",
    reason: "产品手册保持不做（本轮决策）",
  },
  "toolbox/manual/embeds/ManualApprovalCardPreview": {
    verdict: "simplified",
    reason: "产品手册内嵌预览，手册保持不做（本轮决策）",
  },
  "toolbox/manual/embeds/ManualCheckpointCardPreview": {
    verdict: "simplified",
    reason: "产品手册内嵌预览，手册保持不做（本轮决策）",
  },
  "toolbox/manual/embeds/ManualDebateFinalePreview": {
    verdict: "simplified",
    reason: "产品手册内嵌预览，手册保持不做（本轮决策）",
  },
  "toolbox/manual/embeds/ManualDebateScoreboardPreview": {
    verdict: "simplified",
    reason: "产品手册内嵌预览，手册保持不做（本轮决策）",
  },
  "more/AppearanceSettings": {
    verdict: "simplified",
    reason: "手机不提供外观/暗色切换（明确决策）",
  },

  // —— 物理做不到（绑桌面画布 / 硬件）——
  WhiteboardPage: {
    verdict: "impossible",
    reason: "协作白板入口，手机无板（与 board_* 事件同裁）",
  },
  WhiteboardCanvasPage: {
    verdict: "impossible",
    reason: "协作白板画布，手机无板",
  },
  WhiteboardPreviewPage: {
    verdict: "internal",
    reason:
      "桌面白板离线自检回放（#/preview/whiteboard 开发工具），非用户产品面",
  },
  "simulation/TownLauncherPage": {
    verdict: "impossible",
    reason: "AI 小镇 AgentTown 独立客户端启动页，桌面专属，手机无模拟面",
  },
  "more/ShortcutsSettings": {
    verdict: "impossible",
    reason: "手机无物理键盘，快捷键设置无意义",
  },

  // —— infra / 渲染叶 / 桶文件 / 开发自检（非用户-对等面）——
  ConversationsPage: {
    verdict: "internal",
    reason: "桶文件 re-export ./conversations/ConversationsPage",
  },
  "more/SettingsHeader": {
    verdict: "internal",
    reason: "设置页共享头部渲染叶（非独立面）",
  },
  "toolbox/manual/primitives": {
    verdict: "internal",
    reason: "产品手册渲染基件（非独立面）",
  },
  "toolbox/manual/BlockRenderer": {
    verdict: "internal",
    reason: "产品手册渲染基件（非独立面）",
  },
  "toolbox/manual/ChapterRenderer": {
    verdict: "internal",
    reason: "产品手册渲染基件（非独立面）",
  },
  "toolbox/manual/renderRichText": {
    verdict: "internal",
    reason: "产品手册富文本渲染基件（非独立面）",
  },
  PreviewPage: {
    verdict: "internal",
    reason: "桌面渲染层离线自检回放（#/preview 开发工具），非用户产品面",
  },
  CapabilityPacksPreviewPage: {
    verdict: "internal",
    reason: "桌面能力包离线自检预览（#/preview 开发工具），非用户产品面",
  },
  AskCommencePreviewPage: {
    verdict: "internal",
    reason:
      "桌面已退役 ask 开场布局对照（#/preview/ask-commence）；现生产 = AskDecisionBody，非用户产品面",
  },
  ConversationsPreviewPage: {
    verdict: "internal",
    reason:
      "桌面会话管理页离线预览（#/preview/conversations 开发自检），非用户产品面",
  },
  "conversations/ConversationManageRow": {
    verdict: "internal",
    reason: "会话管理列表行渲染叶（ConversationsPage 拆件，非独立面）",
  },
  "conversations/ArchivedConversationManageRow": {
    verdict: "internal",
    reason: "已归档会话列表行渲染叶（ConversationsPage 拆件，非独立面）",
  },
  "conversations/CollaborationTimeline": {
    verdict: "simplified",
    surface: "CollaborationSummaryList（工作区文件页文字摘要）",
    reason: "桌面项目协作时间线+阶段产物；手机降级为文字摘要列表，无可缩放大图",
  },
  TurnDetailPage: {
    verdict: "simplified",
    reason: "桌面 run 详情全页；手机在 TeamView / 气泡内嵌简版",
  },

  // —— 法律文案（登录前 / 关于页入口）——
  "legal/LegalDocBody": {
    verdict: "ported",
    surface: "legal/LegalDocBody",
  },
  "legal/LegalDocPane": {
    verdict: "ported",
    surface: "legal/LegalDocPage（登录前全页阅读）",
  },
  "legal/LegalSettingsPage": {
    verdict: "ported",
    surface: "more/AboutSettings → /legal/:docId（LegalDocPage）",
  },
};
