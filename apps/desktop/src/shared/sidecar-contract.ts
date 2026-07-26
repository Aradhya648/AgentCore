/**
 * Sidecar IPC 契约 —— 主进程 / preload / renderer 三端共享的单一真相源。
 *
 * sidecar（双模式工作区 / 远期规划 §一.1）是跑在用户本机的 Python 进程，**托管同一个
 * 运行时引擎**：桌面 spawn `python -m agentcore.sidecar`，经 stdio JSON-RPC 驱动它，
 * 一个回合完全在本机执行（文件 / 代码直接碰真实本地盘，不再每个 op 经 `WorkspaceChannel`
 * 往返云端）。
 *
 * 本文件只定义「主进程 ↔ renderer」这一段 IPC 的形状；主进程内部再把它翻译成与 Python
 * sidecar 之间的 JSON-RPC（见 `main/sidecar-service.ts`）。两侧字段刻意对齐 Python 端
 * `agentcore/sidecar/server.py` 的参数 / 返回，避免契约漂移。
 *
 * 与 `ipc-contract.ts`（本地文件系统）分文件：那是「云端引擎遥控桌面执行 op」的通道，
 * 本文件是「引擎本体就在本地」的通道，两者是双模式的两条独立链路。
 */

/** 一次回合的云代理推理凭据：把引擎的 LLM 调用指向云端推理代理（平台 key 不下放本机）。 */
export interface SidecarInference {
  baseUrl: string;
  apiKey: string;
  /** 服务端在铸 inference token 时解析的上游模型名（与推理代理一致）。 */
  model: string;
}

/** 会话权限模式三档（安全权限与治理 · 会话级权限模式）——与服务端 `PermissionPreset` 枚举逐字对齐。
 *  sidecar 无会话库，桌面按回合把当前会话模式随参数送达本地引擎。 */
export type SidecarPermissionPreset = "observe" | "workspace" | "full_trust";

/** renderer 发起一次本地回合所需的入参（主进程据此驱动对应 root 的 sidecar）。 */
export interface SidecarStartTurnRequest {
  /** 目标会话 id —— 回流的 `turn/event` 用它定位 renderer 侧的会话切片。 */
  conversationId: string;
  /** 绑定的本地授权根 id（主进程据此解析绝对路径并复用 / 拉起该根的 sidecar）。 */
  rootId: string;
  /** 工作区子路径（工作区对称化 D1a）：非空时主进程把 sidecar 的 `workspaceRoot` 设为
   *  `容器根 absPath + subpath`，故懒建的 per 对话本地工作区各跑在自己目录里。缺省 / 空 =
   *  该根自身（显式添加的本地项目，现行为）。sidecar 按 `rootId + subpath` 分别起进程。 */
  subpath?: string;
  /** 本回合 id（cancel 的寻址键；renderer 自行铸造，需在该 sidecar 内唯一）。 */
  turnId: string;
  /** 本回合 trace_id（renderer 铸，32-hex，与服务端 new_trace_id 同形）：随每次云代理 LLM
   *  调用作 header 上报、并随回写落库到 assistant 消息，使推理日志↔气泡归并为同一条 trace
   *  （打通气泡↔日志）。 */
  traceId: string;
  /**
   * 本轮用户气泡的乐观 id（干净 UUID）——outbox 幂等锚（as-built: 双模式工作区 §10.3）。
   * 主进程回写器据此组 `RecordTurnRequest.user_message_id`，与云端 finalize 去重对齐。
   */
  userMessageId: string;
  /** 用户本轮消息正文。 */
  userMessage: string;
  /**
   * 先前对话历史（`{role, content}` 列表）。云模式由服务端从库里取；sidecar 无库
   * （Slice 1 的 `ConversationStore` 为 no-op），故由 renderer 从本地会话切片喂入。
   */
  history?: SidecarHistoryEntry[];
  /** 云代理凭据；缺省则 sidecar 回退到其自身 server 配置（dev 便利，非生产姿态）。 */
  inference?: SidecarInference;
  /** 本会话当前权限模式。缺省 = sidecar 沿用当前值（初始默认 workspace）。 */
  permissionPreset?: SidecarPermissionPreset;
}

/** 一条历史消息（与引擎 `run_chat_pipeline` 的 history 形状对齐）。 */
export interface SidecarHistoryEntry {
  role: "user" | "assistant";
  content: string;
}

/** 一条 web 来源（对齐服务端 `Citation`：url/title/snippet/site 恒在；台账加宽字段可选）。
 *  主进程 writebacker 原样写入 `POST .../local-turns`，故须与生成类型逐字段同形。 */
export interface SidecarCitation {
  url: string;
  title: string;
  snippet: string;
  site: string;
  id?: string | null;
  date?: string | null;
  tier?: string | null;
  query?: string | null;
  deep_read?: boolean | null;
  registrant?: string | null;
  citable?: boolean | null;
}

/** 回合调研台账条目（对齐服务端 `EvidenceLedgerEntryRest` / SSE TurnEvidenceLedgerEntry）。 */
export interface SidecarEvidenceLedgerEntry {
  id: string;
  url?: string;
  title?: string;
  snippet?: string;
  site?: string;
  date?: string;
  tier?: string;
  query?: string;
  deep_read?: boolean;
  registrant?: string;
  citable?: boolean;
}

/** 回合回放载荷（**严格**对齐服务端 `RunsPayload` schema：多 Agent 团队图事件 + 单 Agent
 *  思考·工具时间线 + per-run worker process）。主进程 writebacker **原样**写入云端落库，
 *  renderer 自身不解读；字段可选性与生成类型一致。 */
export interface SidecarRunsPayload {
  events?: Record<string, unknown>[];
  finish_reason?: string | null;
  process?: Record<string, unknown>[] | null;
  /** Per-run ProcessStep[] map (run_id → steps); mirrors RunsPayload.run_processes. */
  run_processes?: Record<string, Record<string, unknown>[]> | null;
}

/** 一次回合的最终结果（startTurn 的延迟响应——流式细节已由 `turn/event` 给过）。 */
export interface SidecarTurnResult {
  turnId: string;
  messageId: string | null;
  content: string;
  reasoningContent: string | null;
  finishReason: string;
  /** The chat model this turn ACTUALLY ran on (`resolve_turn_model` inside the sidecar): the
   *  cloud-proxy/account model when an inference token was present, else the local platform
   *  model on the dev fallback. The renderer surfaces it on the model badge. */
  model: string;
  rounds: number;
  /** 全量 token 快照（引擎记账的五项）——原样回写落 `Message.usage`，使 sidecar 回合重载后
   *  的 meta 行与云回合一致（云 `persist_turn_result` 落同样键）。成本不随行（云代理权威计费）。 */
  usage: {
    inputTokens: number;
    outputTokens: number;
    reasoningTokens: number;
    cacheHitTokens: number;
    cacheMissTokens: number;
  };
  /** 助手回复的 web 来源（落库到 assistant 消息）。 */
  citations: SidecarCitation[];
  /** 回合调研台账（引用即出处 P1 · Q9）；缺省 []，不得丢 id。 */
  evidence_ledger?: SidecarEvidenceLedgerEntry[];
  /** 回放载荷（团队图 / 思考·工具时间线）；纯聊天回合为 null。 */
  runs: SidecarRunsPayload | null;
  error: string | null;
}

/**
 * 一个等待续跑的「持久挂起回合」摘要（结构化挂起 2b / 双模式工作区 §一.1 durable）。
 *
 * 字段**严格**对齐服务端 `PausedTurnSummary`（snake_case）——renderer 把它**原样**喂给
 * 同一个 `usePausedTurnStore.setForConversation`（云 / 本地共用一套挂起卡渲染，零重映射，
 * 同 `SidecarRunsPayload` 对齐云 schema 的姿态）。sidecar 回合暂停于 plan_review / ask_user 检查点
 * 且应用关闭后，帧落本机文件；重开会话时由主进程直接读盘列出（不拉起 Python）。
 */
export interface SidecarPausedTurn {
  message_id: string;
  /** 暂停点类型——决定续跑卡片形态。 */
  kind: "plan_review" | "ask_user";
  checkpoint_id: string;
  user_message: string;
  /** Client-minted id of the user bubble (pinned on pause write-back). */
  user_message_id?: string;
  /** plan_review：被复核的检查点步 / 被门控的下游步（ask_user 帧为空）。 */
  steps: Record<string, unknown>[];
  pending: Record<string, unknown>[];
  /** ask_user：统一卡片载荷（plan_review 帧为空）。 */
  question: string;
  context: string;
  assumptions: Record<string, unknown>[];
  questions: Record<string, unknown>[];
  style_options: Record<string, unknown>[];
}

/** 续跑一个持久挂起的本地回合（结构化挂起 2b resume，经 sidecar 的 `resume` 方法）。 */
export interface SidecarResumeRequest {
  rootId: string;
  /** 工作区子路径（同 `SidecarStartTurnRequest.subpath`）：寻址按 root+subpath 起的进程。 */
  subpath?: string;
  conversationId: string;
  /** 挂起回合的 assistant message_id（续跑键；续跑后的回复复用它）。 */
  messageId: string;
  /** 本次续跑的 trace_id（同 {@link SidecarStartTurnRequest.traceId}）：续跑也跑 LLM，故
   *  随云代理调用上报、并随回写落库，使这次续跑的推理↔气泡归并为同一条 trace。 */
  traceId: string;
  /** 挂起时已落库的原始 user 气泡 id —— outbox 幂等锚（同 startTurn.userMessageId）。 */
  userMessageId?: string;
  /** continue（授权并开工）/ per_call（历史）/ adjust / stop / research_first（辩论·先调研再辩）。 */
  decision: "continue" | "per_call" | "adjust" | "stop" | "research_first";
  /**
   * continue：可选开工嘱咐（非空则注入未跑队员，与 checkpoints CONTINUE+note 对齐）；
   * adjust：转向说明；stop：收尾语；research_first：忽略 note。
   */
  note: string;
  /** ask_user 的选项选择；plan_review 忽略。 */
  selected?: string[];
  /** Structured website style pick (s0/s1/…). */
  styleId?: string;
  /** Structured presentation format pick (f0/f1/…). */
  formatId?: string;
  /** 云代理凭据（同 `startTurn`）——续跑要跑 LLM；重启后续跑会新拉起引擎，故须随带。 */
  inference?: SidecarInference;
  /** 本会话当前权限模式（同 `startTurn.permissionPreset`）。 */
  permissionPreset?: SidecarPermissionPreset;
}

/** A1+ 本机回合文件真 diff（相对 `.agentcore/baselines/{messageId}.zip`）。 */
export interface SidecarTurnFilesDiffRequest {
  rootId: string;
  subpath?: string;
  messageId: string;
  /** Optional; omit → sidecar resolves by messageId path convention. */
  baselineSnapshotId?: string | null;
}

/** Wire shape mirrors cloud ``GET …/files/diff`` (snake_case). */
export interface SidecarTurnFilesDiffResult {
  message_id: string;
  baseline_snapshot_id: string | null;
  available: boolean;
  data: Array<{
    path: string;
    change_type: "added" | "modified" | "deleted";
    base_sha: string | null;
    result_sha: string | null;
    is_binary: boolean;
    content: string | null;
    size_bytes: number;
    base_content?: string | null;
  }>;
  total: number;
  added: number;
  modified: number;
  deleted: number;
}

/** A2′ 本机回退到回合基线（unzip 覆盖工作区，不经云 restore）。 */
export interface SidecarRestoreTurnBaselineRequest {
  rootId: string;
  subpath?: string;
  snapshotId: string;
}

/**
 * Build the Python JSON-RPC ``resume`` params from a renderer IPC request.
 *
 * ``rootId`` / ``subpath`` are main-process routing only — they never cross stdio.
 * ``selected`` is always sent (empty array when absent) so Python never has to guess.
 */
export function buildSidecarResumeRpcParams(
  req: Pick<
    SidecarResumeRequest,
    | "messageId"
    | "conversationId"
    | "traceId"
    | "decision"
    | "note"
    | "selected"
    | "styleId"
    | "formatId"
    | "userMessageId"
    | "permissionPreset"
  >,
  inference?: SidecarInference,
): Record<string, unknown> {
  return {
    messageId: req.messageId,
    conversationId: req.conversationId,
    traceId: req.traceId,
    decision: req.decision,
    note: req.note,
    selected: req.selected ?? [],
    ...(req.styleId ? { styleId: req.styleId } : {}),
    ...(req.formatId ? { formatId: req.formatId } : {}),
    ...(req.userMessageId ? { userMessageId: req.userMessageId } : {}),
    ...(inference ? { inference } : {}),
    ...(req.permissionPreset ? { permissionPreset: req.permissionPreset } : {}),
  };
}

/** 探活一个 `root + subpath` 的 sidecar：拉起进程并完成 initialize 握手即返回（不跑回合），
 *  用于在首次真正走 sidecar 前提前验证本机环境（Python / venv / 引擎导入 / 工作区绑定）能起
 *  得来（见 renderer `sidecarHealth`）。 */
export interface SidecarProbeRequest {
  rootId: string;
  /** 工作区子路径（同 `SidecarStartTurnRequest.subpath`）：按 root+subpath 寻址进程，使握手成功
   *  留存的进程正好被随后的首个回合复用（零额外拉起）。 */
  subpath?: string;
}

/**
 * 主进程 → renderer 的回合事件推送。`event` 与服务端 SSE 的事件同形状
 * （`@/types/events` 的 `SSEEvent`），故 renderer 可把它**原样**喂给同一个
 * `dispatchSSEEvent`——云 / 本地两条链路共用一套事件处理，零额外分支。
 */
export interface SidecarEventPush {
  conversationId: string;
  turnId: string;
  event: {
    type: string;
    /** ISO-8601 字符串（与引擎 `SSEEvent.timestamp` 一致，便于原样喂 `dispatchSSEEvent`）。 */
    timestamp: string;
    payload: unknown;
  };
}

/** 主进程 → renderer 的 sidecar 生命周期/诊断推送（拉起失败、退出等）。 */
export interface SidecarStatusPush {
  rootId: string;
  /** spawned=已拉起并初始化；exited=进程退出；error=拉起/通信失败。 */
  phase: "spawned" | "exited" | "error";
  /** 人类可读说明（error/exited 时带原因，用于 UI 降级提示与排查）。 */
  detail?: string;
}

/** 结算一个被挂起的交互（审批 / ask_user / 本地工具）——经 sidecar 的 `respond` 方法。 */
export interface SidecarRespondRequest {
  rootId: string;
  /** 工作区子路径（同 `SidecarStartTurnRequest.subpath`）：寻址按 root+subpath 起的进程。 */
  subpath?: string;
  /** 被挂起交互的 id（即引擎 `ClientRequestBridge` 发出的 requestId）。 */
  requestId: string;
  conversationId: string;
  /** 该交互的应答载荷（形状随交互类型而定）。 */
  result: unknown;
}

/** 取消一个在跑的回合。 */
export interface SidecarCancelRequest {
  rootId: string;
  /** 工作区子路径（同 `SidecarStartTurnRequest.subpath`）：寻址按 root+subpath 起的进程。 */
  subpath?: string;
  turnId: string;
  /** 会话 id：sidecar cancel 级联 ``cancel_coordination_on_user_stop`` 用（与云 `/stop` 同语义）。 */
  conversationId?: string;
}

/** 用户中途改某个 worker 的方向（中间可见性 Phase 2a）。 */
export interface SidecarRunRedirectRequest {
  rootId: string;
  subpath?: string;
  conversationId: string;
  executionId: string;
  runId: string;
  feedback: string;
}

/** 辩论 ambient 掌舵（fire-and-forget，下一轮边界生效）。 */
export interface SidecarDebateSteerRequest {
  rootId: string;
  subpath?: string;
  conversationId: string;
  executionId: string;
  decision: "continue" | "conclude";
  focus?: string;
  ask?: string;
  askTarget?: string;
}

/** 本机 outbox 未同步回合的投影自足摘要（recovery → renderer D5，不透传 journal）。 */
export interface SidecarUnsyncedTurnSummary {
  user_message_id: string;
  user_message: string;
  message_id: string | null;
  trace_id: string;
  /** `dead` = permanent writeback failure (dead-letter/), still recoverable in UI. */
  phase: "open" | "ready" | "dead";
  updated_at: number;
  content: string;
  reasoning_content: string | null;
  citations: SidecarCitation[];
  evidence_ledger?: SidecarEvidenceLedgerEntry[];
  runs: SidecarRunsPayload | null;
  finish_reason: string | null;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
}

/** 查询某会话的本地恢复面（活回合 + 未同步 outbox 摘要 + 挂起帧）。 */
export interface SidecarRecoveryRequest {
  conversationId: string;
}

export interface SidecarRecoveryResponse {
  liveRunning: boolean;
  /** 活回合键（startTurn=`turnId`，resume=`messageId`）。 */
  turnId?: string;
  unsynced: SidecarUnsyncedTurnSummary[];
  /** 本机冷路挂起帧（与原 listPaused 同源；一次 IPC 拿全本地事实）。 */
  paused: SidecarPausedTurn[];
}

/** 重绑本窗口并取回缓冲事件快照（零 await 段在主进程 handler 内）。 */
export interface SidecarAttachRequest {
  conversationId: string;
}

export interface SidecarAttachResponse {
  attached: boolean;
  turnId?: string;
  rootId?: string;
  subpath?: string;
  /** startTurn 登记；resume 类可能缺省。 */
  userMessageId?: string;
  userMessage?: string;
  traceId?: string;
  /** resume 类活回合的助手行锚（= 登记键 messageId）。 */
  messageId?: string;
  /** `"start"` | `"resume"` —— renderer 据此选择 clear-then-fold vs 增量 fold。 */
  kind?: "start" | "resume";
  /** 裸 SSE 事件（与 `dispatchSSEEvent` 同形）；非 `SidecarEventPush` 信封。 */
  events?: Array<{
    type: string;
    timestamp: string;
    payload: unknown;
  }>;
}

/** IPC 通道名 —— 主进程与 preload 共用，避免硬编码漂移。 */
export const SIDECAR_CHANNELS = {
  startTurn: "sidecar:startTurn",
  cancel: "sidecar:cancel",
  respond: "sidecar:respond",
  runRedirect: "sidecar:runRedirect",
  debateSteer: "sidecar:debateSteer",
  resume: "sidecar:resume",
  probe: "sidecar:probe",
  recovery: "sidecar:recovery",
  attach: "sidecar:attach",
  turnFilesDiff: "sidecar:turnFilesDiff",
  restoreTurnBaseline: "sidecar:restoreTurnBaseline",
  event: "sidecar:event",
  status: "sidecar:status",
} as const;

/**
 * 暴露在 `window.sidecarApi` 上的 renderer 端 API 面。
 *
 * `startTurn` 的 Promise 在**回合结束**时才 resolve（携带最终结果）；过程中的流式
 * 事件经 `onEvent` 推来。失败（拉起不了 sidecar / 引擎异常）以 reject 抛出，调用方
 * 据此降级（如退回云模式或提示）。
 */
export interface SidecarApi {
  startTurn(req: SidecarStartTurnRequest): Promise<SidecarTurnResult>;
  cancel(req: SidecarCancelRequest): Promise<void>;
  respond(req: SidecarRespondRequest): Promise<{ resolved: boolean }>;
  runRedirect(req: SidecarRunRedirectRequest): Promise<void>;
  debateSteer(req: SidecarDebateSteerRequest): Promise<void>;
  /** 续跑一个持久挂起的本地回合；Promise 在续跑结束时 resolve（同 `startTurn` 携最终结果，
   * 过程事件经 `onEvent` 推来）。 */
  resume(req: SidecarResumeRequest): Promise<SidecarTurnResult>;
  /** 探活一个 root 的 sidecar（拉起 + initialize 握手即返回，不跑回合）。成功 = 本机环境能起
   * 本地引擎（握手成功的进程留存、被首个回合复用）；失败 reject（诊断经 `onStatus` 推送）。 */
  probe(req: SidecarProbeRequest): Promise<void>;
  /** 查询本地恢复面（活回合 + 未同步 outbox + 挂起帧）；零 spawn。 */
  recovery(req: SidecarRecoveryRequest): Promise<SidecarRecoveryResponse>;
  /** 重绑本窗口并取回缓冲事件快照 + 续流；`attached:false` 时走投影/ghost 降级。 */
  attach(req: SidecarAttachRequest): Promise<SidecarAttachResponse>;
  /** A1+ 本机回合文件真 diff（相对工作区旁基线 zip）。 */
  turnFilesDiff(
    req: SidecarTurnFilesDiffRequest,
  ): Promise<SidecarTurnFilesDiffResult>;
  /** A2′ 本机回退到回合基线（unzip 覆盖，不经云）。 */
  restoreTurnBaseline(req: SidecarRestoreTurnBaselineRequest): Promise<void>;
  /** 订阅本回合事件流；返回取消订阅函数。 */
  onEvent(cb: (e: SidecarEventPush) => void): () => void;
  /** 订阅 sidecar 生命周期/诊断事件；返回取消订阅函数。 */
  onStatus(cb: (e: SidecarStatusPush) => void): () => void;
}
