import type { ErrorAction } from "@/lib/errors";
import type { ExecutionJournal } from "@/stores/execution";
import type {
  AskAssumption,
  AskQuestion,
  AskStyleOption,
  CeoReviewSummary,
  CheckpointDecision,
  CheckpointIntent,
  Citation,
  ContextBlockWire,
  CostBreakdown,
  PlanReviewPending,
  PlanReviewStep,
  ProcessStep,
  UsageBreakdown,
} from "@/types/events";
import type { TurnPhase } from "./turnPhase";

export interface CheckpointDisplay {
  id: string;
  question: string;
  context: string;
  assumptions: AskAssumption[];
  questions: AskQuestion[];
  styleOptions: AskStyleOption[];
  intent: CheckpointIntent;
  status: "pending" | "resolved";
  decision: CheckpointDecision | null;
  note: string;
  selected: string[];
}

export interface NonBlockingAskDisplay {
  id: string;
  question: string;
  context: string;
  assumptions: AskAssumption[];
  questions: AskQuestion[];
  styleOptions: AskStyleOption[];
}

export interface PlanReviewDisplay {
  id: string;
  steps: PlanReviewStep[];
  pending: PlanReviewPending[];
  status: "pending" | "resolved";
  decision: CheckpointDecision | null;
  note: string;
  /** 主 Agent 暂停前的把关摘要（拍板中心专属展示；旧数据 absent → 不渲染）。 */
  ceoReview?: CeoReviewSummary;
}

export interface TeamPreviewWorkerDisplay {
  run_id: string;
  role: string;
  task: string;
  depends_on: string[];
  debate: boolean;
}

export interface TeamPreviewSideDisplay {
  key: string;
  name: string;
  stance: string;
  is_subject?: boolean;
}

export type KickoffPrimitive = "delegate" | "debate";

export interface TeamPreviewDisplay {
  id: string;
  /** Orchestration primitive — drives card layout (分工表 vs 辩题/立场). */
  primitive: KickoffPrimitive;
  workers: TeamPreviewWorkerDisplay[];
  /** Grantable tools listed on the kickoff card (may be empty under full_auto). */
  tools: string[];
  motion: string;
  form: string;
  sides: TeamPreviewSideDisplay[];
  maxRounds: number;
  thorough: boolean;
  /** Debate kickoff: offer「先多视角调研再辩」(缺省 false). */
  offerResearchFirst: boolean;
  /** Debate kickoff: elevate research-first as visual primary (缺省 false). */
  researchFirstRecommended: boolean;
  status: "pending" | "resolved";
  decision: CheckpointDecision | null;
  note: string;
}

export interface Conversation {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  lastMessagePreview: string | null;
  folderId?: string | null;
  localContainerRootId?: string | null;
  /**
   * Optimistic: folder bound via delivery/ask bind card (列表 API 暂无此字段).
   * Sidecar 寻址：`cache.rootId ?? localRootId ?? localContainerRootId`.
   */
  localRootId?: string | null;
  pinned?: boolean;
  archived?: boolean;
  /** Session permission mode (observe | workspace | full_trust). */
  permissionPreset?: "observe" | "workspace" | "full_trust";
  /**
   * 会话级模型覆盖（会话级模型切换）：非空即「本会话固定跑这个模型」，从当前回合起生效；
   * null/缺省 = 跟随账号默认（`ModelCatalogResponse.current`）。源自 `ConversationSummary.model`，
   * 由输入框的 {@link import("@/components/chat/message-input/ModelPicker").ModelPicker} 写入。
   */
  model?: string | null;
  /** 与 `model` 成对的凭据来源（byok / platform）；清除覆盖时一并 null。 */
  modelOrigin?: ("byok" | "platform") | null;
  /**
   * 与 `model` 成对、当 `modelOrigin === "byok"` 时**必填**的服务商 id（多服务商消歧）：
   * 同一模型 id 可在多个 BYOK 服务商下重复出现。源自 `ConversationSummary.model_provider_id`；
   * platform / 清除覆盖时为 null。
   */
  modelProviderId?: string | null;
}

export interface MessageAttachmentMeta {
  id: string;
  name: string;
  path: string;
  truncated: boolean;
  kind?: "file" | "dir" | "conversation";
  workspacePath?: string;
  conversationId?: string;
}

/** One applied change in a「记忆已更新」card (记忆更新对话内可见, Agent记忆与知识系统 §1.6).
 * `file` is a friendly label (偏好 / 画像 / 主题·<slug>); `scope` is `"global"` |
 * `"project"`; `content` is the bullet (add/update) or matched text (remove); `target`
 * is the synthetic memory-leaf path the card deep-links to (`""` = no leaf). */
export interface MemoryUpdateItem {
  action: string;
  file: string;
  section: string;
  scope: string;
  content: string;
  target: string;
  /** Project folder id when ``scope`` is ``project`` (深链展开该项目「记忆」节点). */
  projectId?: string | null;
}

/** One memory-write notice on the conversation timeline (two-layer memory).
 * `kind: "episodic"` → light tip (`summary`); `kind: "semantic"` → diff card (`items`).
 * Loaded with the latest messages window + pushed live on the firehose (`memory_updated`). */
export interface MemoryUpdate {
  id: string;
  createdAt: string;
  kind: "episodic" | "semantic";
  summary?: string | null;
  items: MemoryUpdateItem[];
}

export interface Message {
  id: string;
  /** 挂起即收口 (②): the SERVER's assistant message_id from `message_start` (the live
   * bubble's own `id` is a client UUID). It is the resume KEY — the id a durable frame is
   * persisted under and that `POST .../resume` claims — so a turn that ends paused
   * in-session must surface its resume card keyed by THIS, not the client id (which 404s).
   * Absent until message_start stamps it on the live path; on reload `toMessage` sets it
   * to the persisted row id (already the server id) so resume guards stay live-aligned. */
  serverMessageId?: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  process?: ProcessStep[];
  createdAt: string;
  executionId: string | null;
  isStreaming: boolean;
  /**
   * Local-only outbox sync hint for sidecar turns (as-built: 前端 UX §一B；双模式 §10.3).
   * `synced_pending` = on disk, cloud not acked; `synced` = cloud just acked.
   * Never on SSE / REST / conformance — desktop UI only.
   */
  syncStatus?: "synced_pending" | "synced";
  /** Progressive assistant-row lifecycle from ``messages.usage.status`` (P1 overlay /
   * P4 hydrate). ``running`` → stream-style partial; ``incomplete`` → interrupted
   * affordance. null for user / pre-feature rows. */
  status?: "running" | "complete" | "incomplete" | "failed" | null;
  composingTool?: { toolName: string; chars: number } | null;
  attachments?: MessageAttachmentMeta[];
  citations?: Citation[];
  /** 回合调研台账（`evidence_ledger` SSE / Message.evidence_ledger）；缺省 []。 */
  evidenceLedger?: import("@/types/events").TurnEvidenceLedgerEntry[];
  cost?: CostBreakdown;
  usage?: UsageBreakdown;
  rounds?: number;
  finishReason?: string;
  /** 协作质量 (学·度量 §2.5): turn-level orchestration signals. Live via
   * message_end; reload via messages API (nested in usage column). Orchestration
   * counts also surface in the assistant footer; audit_drops is diagnostic-only. */
  collab?: import("@/types/events").TurnCollabMetrics;
  runs?: ExecutionJournal;
  captainContext?: ContextBlockWire[];
  error?: {
    code: string;
    message: string;
    context?: {
      upstream_status?: number;
      upstream_body_preview?: string | null;
      retry_attempts?: number;
      empty_diagnosis?: string;
      sub2api_diagnosis?: string;
      sub2api_account?: string;
    };
  };
  /** CEO→用户「下一步推荐」(下一步推荐): post-turn quick-reply suggestions, shown as
   * one-click chips under the latest assistant turn (fill the composer on click).
   * DERIVED-persisted (messages.followups column, twin of the title): live they ride
   * `followups_generated` (matched by `message_id` → `id || serverMessageId`); on reload
   * `toMessage` replays them so reopening a conversation still shows the last turn's chips. */
  followups?: string[];
  /** 回复反馈 (点赞/点踩, 对话基础功能补齐): the user's satisfaction rating on this assistant
   * reply — `"up"` / `"down"`, or `null` / undefined for 未评价. Persisted (messages.feedback
   * column) so a reloaded bubble replays the rating; toggled via the footer thumbs. */
  feedback?: "up" | "down" | null;
  traceId?: string;
  /** Preflight soft gate when the configured model may lack tool calling (turn_warning SSE). */
  turnWarning?: string;
  /**
   * 消息归因（如 `execution_harvest` 系统收口）。REST 暂未暴露 metadata 时由
   * {@link import("@/lib/executionHarvest").isExecutionHarvestMessage} 从正文前缀推断。
   */
  origin?: string | null;
}

export interface ConversationRuntime {
  messages: Message[];
  /** Conversation-tail「记忆已更新」cards (记忆更新对话内可见, §1.6): what the AI
   * remembered FROM this conversation, appended after the last message. Loaded with
   * the latest window + appended live from the firehose. */
  memoryUpdates: MemoryUpdate[];
  isGenerating: boolean;
  /**
   * 回合停止生命周期（键随本切片 = conversationId）。
   * idle → preflight → streaming → stopping → stopped|completed|failed。
   * Abort 只断流；开流门禁与迟到事件过滤以本字段为准。
   */
  turnPhase: TurnPhase;
  abort: AbortController | null;
  error: string | null;
  retry: (() => void) | null;
  errorAction: ErrorAction | null;
  messageFocus: { id: string; nonce: number } | null;
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  loadingOlder: boolean;
  loadingNewer: boolean;
  /** turn_warning received before message_start — stamped onto the next assistant bubble. */
  pendingTurnWarning: string | null;
  /** 桌面本地 · live-only：每个 CEO 工具调用的真实开始时刻（epoch ms，键 = tool_call_id）。
   * ToolLine 的「运行 · Ns」计时锚定于此而非组件挂载时刻，故过程折叠/展开、聊天列表虚拟化
   * 重挂后仍准。`addProcessTool` 盖章、`endProcessTool` 清理；不落 journal（重载后工具已完成，
   * 无需再计时），也不进 conformance ProjectedTurn——同 {@link ProcessStep} tool 步的 `phase`
   * 一样是仅生产流盖的短命态。 */
  toolStartedMs: Record<string, number>;
}
