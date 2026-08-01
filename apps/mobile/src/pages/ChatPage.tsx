import { getTokens } from "@/api/client";
import {
  type MemoryUpdate,
  type MessageDetail,
  createConversation,
  getConversation,
  getMessages,
  setConversationModelProfile,
} from "@/api/conversations";
import { sendMidFlightMessage } from "@/api/midFlight";
import {
  clearLastModelProfileId,
  getLastModelProfileId,
  profileDisplayLabel,
  setLastModelProfileId,
  useModelProfiles,
} from "@/api/modelProfiles";
import { resolveStageCardStream } from "@/api/stageCard";
import {
  attachStream,
  regenerateStream,
  resumeStream,
  streamMessage,
} from "@/api/stream";
import {
  type PausedTurnSummary,
  type PendingInteractionSummary,
  type TurnRecovery,
  getRecovery,
  stopConversation,
} from "@/api/turn";
import { getMessageCostDisplay } from "@/api/usage";
import {
  AssistantContent,
  SupportDiagnosticCopyButton,
} from "@/components/AssistantView";
import { ConversationDrawer } from "@/components/ConversationDrawer";
import { DelegationAuthorizationCard } from "@/components/DelegationAuthorizationCard";
import { FileArtifactsCard } from "@/components/FileArtifactsCard";
import { MemoryUpdateCard } from "@/components/MemoryUpdateCard";
import { ModelPicker } from "@/components/ModelPicker";
import { PauseCard } from "@/components/PauseCard";
import { ResumeCard } from "@/components/ResumeCard";
import { StageCard } from "@/components/StageCard";
import { VoiceButton, VoiceRecordingBar } from "@/components/VoiceInput";
import { type MessageAttachment, readTextAttachment } from "@/lib/attachments";
import {
  type ErrorAction,
  StreamHttpError,
  describeStreamHttpError,
  emptyChatCopy,
  emptyFailureNotice,
} from "@/lib/errors";
import { resolveFileArtifactsForCard } from "@/lib/fileArtifacts";
import {
  createHarvestRefreshScheduler,
  dropSettledLiveTurns,
} from "@/lib/refreshAfterExecutionCompleted";
import {
  STOPPED_LABEL,
  STOP_FAILED_MESSAGE,
  STOP_RETRY_LABEL,
  STOP_UNCONFIRMED_MESSAGE,
  type StopUiPhase,
  allowsEventWhileStopping,
  createStopConfirmTimer,
  isStopBusy,
  isStopConfirmEvent,
  reduceStopPhase,
  stopButtonLabel,
} from "@/lib/stopLifecycle";
import {
  type SupportDiagnosticIds,
  extractSupportIdsFromEvents,
} from "@/lib/supportDiagnostics";
import { useStickScroll } from "@/lib/useStickScroll";
import { useVoiceInput } from "@/lib/useVoiceInput";
import {
  extractAsks,
  extractEscalationSlots,
  extractEvidenceLedger,
  extractFollowups,
  extractFollowupsUnavailable,
  extractGraphAppendActKinds,
  extractGraphAppendAuthorizedBy,
  extractHotDecisionTraces,
  extractRunToolCalls,
  extractStageCardTraces,
  extractToolPhases,
  extractTurnQueued,
  extractWorkerToolPhases,
  fold,
} from "@/protocol/fold";
import type {
  CheckpointDecision,
  DebateNarrativeRound,
  MessageEndPayload,
  SSEEvent,
  TurnWarningPayload,
} from "@agentcore/contract-types";
import type {
  ProjectedInteraction,
  ProjectedTurn,
} from "@agentcore/protocol-conformance";
import {
  ArrowDown,
  Bot,
  Folder,
  Loader2,
  Menu,
  Send,
  Sparkles,
  Square,
  SquarePen,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

// One-shot handoff from a draft send (at `/`) to the freshly-created conversation's first
// stream (at `/c/:id`). 直接对话: the 对话 tab opens a draft (no server conversation); the
// first send lazily creates one, routes to /c/:id, and the remounted ChatPage picks this up
// to POST+stream that first message (rather than re-attaching to a not-yet-existing run).
// Lives outside React so it survives the / → /c/:id remount; cleared on consume, and a hard
// refresh simply finds it empty (the unsent draft is gone — acceptable).
let pendingFirstSend: {
  id: string;
  text: string;
  attachments: MessageAttachment[];
} | null = null;

// A turn streamed this session. `userText === null` for a turn whose user bubble already
// lives in the persisted history (a reattach on reopen / a durable resume) — only its
// assistant side streams live; a fresh send carries its own user text.
interface Turn {
  id: string;
  userText: string | null;
  events: SSEEvent[];
  // Display-only chips for files this turn carried (the text rode the send body, not here).
  attachments?: { name: string; truncated?: boolean }[];
}

/** Attachment context chips on a user bubble (no download — the text rode the send body and
 *  now lives in the conversation workspace). `已截断` flags a file capped at 256KB. */
function AttachmentChips({
  items,
}: {
  items: { name: string; truncated?: boolean }[];
}) {
  if (items.length === 0) return null;
  return (
    <div className="attach-chips">
      {items.map((a, i) => (
        <span key={`${a.name}-${i}`} className="attach-chip">
          <span aria-hidden>📎</span>
          <span className="attach-chip-name">{a.name}</span>
          {a.truncated && <span className="attach-chip-trunc">已截断</span>}
        </span>
      ))}
    </div>
  );
}

/** Build 排查包 ids for a history assistant row (REST trace_id + journal execution_id). */
function historySupportIds(
  m: MessageDetail,
  conversationId: string | null,
): SupportDiagnosticIds {
  const fromEvents = m.runs?.events?.length
    ? extractSupportIdsFromEvents(m.runs.events)
    : {};
  let executionId = fromEvents.executionId;
  if (!executionId && m.runs?.process) {
    for (const s of m.runs.process) {
      if (s.kind === "team" && s.execution_id) {
        executionId = s.execution_id;
        break;
      }
    }
  }
  return {
    conversationId,
    messageId: m.id,
    traceId: m.trace_id ?? fromEvents.traceId,
    executionId,
  };
}

// A run keeps running detached after a dropped connection (执行与请求解耦 C1 · slice 1a),
// so a transport drop reconnects (rejoins the live run), never resends.
const RECONNECT_BANNER = "连接中断，回合仍在后台继续。点「重连」继续查看。";

/** A turn-level error with an optional one-tap reconnect (a held SSE that dropped while
 *  the run lives on), a stop retry (诚实停止：/stop 失败或未确认), or a config remedy
 *  (e.g.「去配置」→ 模型配置 for LLM_KEY_REQUIRED). */
interface ChatError {
  text: string;
  reconnect?: boolean;
  /** /stop 失败或宽限未确认 — 点「重试停止」再走停止闭环。 */
  retryStop?: boolean;
  action?: ErrorAction;
}

/** The user's 停止 (abort button), never surfaced as an error. */
function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** Format an integer nano-CNY cost as ¥ caption (1 元 = 1e9). Returns null for
 *  0 / unknown so a free turn shows nothing, never「¥0.00」(§7.5). BYOK estimates get ≈. */
function formatCost(
  nanoCny: number | null | undefined,
  estimated = false,
): string | null {
  if (!nanoCny || nanoCny <= 0) return null;
  const yuan = nanoCny / 1e9;
  const body = yuan < 0.01 ? "<¥0.01" : `¥${yuan.toFixed(yuan < 0.1 ? 4 : 2)}`;
  return estimated ? `≈${body} 自带密钥·估算` : body;
}

type CachedDisplayMoney = {
  nano: number;
  estimated: boolean;
  /** BYOK 社区价目未命中（pricing_source=unpriced）：显式标注，金额不出数。 */
  unpriced?: boolean;
};

/** 未计价标注文案（拍板 2026-07-20，与桌面 COST_UNPRICED_LABEL 同口径）。 */
const COST_UNPRICED_LABEL = "自带密钥·未计价";

// A reloaded turn carries no cost in its MessageDetail (the ledger is the truth source);
// fetch it lazily per message, cached module-wide so re-renders / re-opens don't refetch.
const costCache = new Map<string, CachedDisplayMoney>();
const costInflight = new Set<string>();

/** Lazily fetch a persisted turn's cost when its bubble scrolls into view (Intersection
 *  Observer — avoids an open-time request storm over a whole window). Returns the cached
 *  display money; supplementary, so a failure just leaves the row uncosted. */
function useLazyMessageCost(messageId: string): {
  ref: React.RefObject<HTMLDivElement | null>;
  money: CachedDisplayMoney | null;
} {
  const ref = useRef<HTMLDivElement>(null);
  const [money, setMoney] = useState<CachedDisplayMoney | null>(
    () => costCache.get(messageId) ?? null,
  );
  useEffect(() => {
    if (!messageId) return;
    if (costCache.has(messageId)) {
      setMoney(costCache.get(messageId) ?? null);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      obs.disconnect();
      if (costCache.has(messageId)) {
        setMoney(costCache.get(messageId) ?? null);
        return;
      }
      if (costInflight.has(messageId)) return;
      costInflight.add(messageId);
      getMessageCostDisplay(messageId)
        .then((t) => {
          if (!t) return;
          costCache.set(messageId, t);
          setMoney(t);
        })
        .finally(() => costInflight.delete(messageId));
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [messageId]);
  return { ref, money };
}

function recoveredApprovalPending(
  a: PendingInteractionSummary,
): Extract<ProjectedInteraction, { kind: "approval" }> | null {
  if (a.kind !== "approval") return null;
  const p = a.payload ?? {};
  return {
    kind: "approval",
    id: a.id,
    status: "pending",
    toolCallId: typeof p.tool_call_id === "string" ? p.tool_call_id : a.id,
    toolName: typeof p.tool_name === "string" ? p.tool_name : "tool",
    arguments: (p.arguments as Record<string, unknown>) ?? {},
  };
}

function recoveredDelegation(
  a: PendingInteractionSummary,
): Extract<ProjectedInteraction, { kind: "delegation_authorization" }> | null {
  if (a.kind !== "delegation_authorization") return null;
  const p = a.payload ?? {};
  const workers = Array.isArray(p.workers)
    ? (p.workers as Array<Record<string, unknown>>)
    : [];
  const tools = Array.isArray(p.tools)
    ? p.tools.filter((t): t is string => typeof t === "string")
    : [];
  return {
    kind: "delegation_authorization",
    id: a.id,
    status: "pending",
    executionId: typeof p.execution_id === "string" ? p.execution_id : "",
    workers,
    tools,
  };
}

function recoveredStageCard(
  a: PendingInteractionSummary,
): Extract<ProjectedInteraction, { kind: "stage_card" }> | null {
  if (a.kind !== "stage_card") return null;
  const p = a.payload ?? {};
  const sides = Array.isArray(p.sides)
    ? (p.sides as Array<Record<string, unknown>>).map((s) => ({
        key: typeof s.key === "string" ? s.key : "",
        name: typeof s.name === "string" ? s.name : "",
        stance: typeof s.stance === "string" ? s.stance : "",
      }))
    : [];
  const ptrs = Array.isArray(p.fact_pointers)
    ? p.fact_pointers.filter((x): x is string => typeof x === "string")
    : [];
  return {
    kind: "stage_card",
    id: a.id,
    status: "pending",
    motion: typeof p.motion === "string" ? p.motion : "",
    sides,
    form: typeof p.form === "string" ? p.form : "debate",
    rationale: typeof p.rationale === "string" ? p.rationale : "",
    factPointers: ptrs,
    thorough: p.thorough !== false,
    maxRounds: Number(p.max_rounds ?? 5) || 5,
    note: typeof p.note === "string" ? p.note : null,
  };
}

/** One-line status derived from the projected turn — proves the fold drives the UI
 * (进度 / 工具 are read off ProjectedTurn, not re-parsed from events). A `paused` turn
 * returns null: its actionable surface owns the view instead — an `approval` pause shows the
 * PauseCard above the composer, while 挂起即收口 (②, Phase 3) a checkpoint / plan_review pause
 * finalizes the turn and shows the durable ResumeCard below it. */
function summarize(p: ProjectedTurn): string | null {
  if (p.status === "paused") return null;
  if (p.runs.length > 0) {
    const running = p.runs.filter((r) => r.status === "running").length;
    return `团队 ${p.progress.completed}/${p.progress.total} 完成${running ? ` · ${running} 进行中` : ""}`;
  }
  const tool = [...p.process].reverse().find((s) => s.kind === "tool");
  if (tool && tool.kind === "tool" && tool.status === "running")
    return `正在调用 ${tool.tool_name}…`;
  if (p.status === "failed") return "出错了";
  if (p.status === "cancelled") return STOPPED_LABEL;
  return null;
}

function extractTurnWarning(events: SSEEvent[]): string | null {
  for (const e of events) {
    if (e.type === "turn_warning") {
      return (e.payload as TurnWarningPayload).message;
    }
  }
  return null;
}

function AssistantBubble({
  turn,
  live,
  conversationId,
  onFill,
}: {
  turn: Turn;
  live: boolean;
  conversationId: string | null;
  onFill: (text: string) => void;
}) {
  const p = useMemo(() => fold(turn.events), [turn.events]);
  // 本回合产出文件：只认 delivery_status.artifacts（缺字段 → 空）。
  const artifacts = useMemo(
    () => resolveFileArtifactsForCard(p.deliveryStatus),
    [p.deliveryStatus],
  );
  // 非阻塞提问卡内容：随时间线 `ask` 标记原位呈现（旁路读原始事件，不入 ProjectedTurn）。
  const asks = useMemo(() => extractAsks(turn.events), [turn.events]);
  // 升级时间线槽（统一时间线二期）: escalation_id → card body（旁路；golden escalations 不加 id）。
  const escalationSlots = useMemo(
    () => extractEscalationSlots(turn.events),
    [turn.events],
  );
  // 热审批/委派授权痕迹 (D3): resolved 轻行内容（旁路读原始事件）。
  const hotTraces = useMemo(
    () => extractHotDecisionTraces(turn.events),
    [turn.events],
  );
  const stageCardTraces = useMemo(
    () => extractStageCardTraces(turn.events),
    [turn.events],
  );
  // 工具执行阶段进度 (联网搜索前端展示优化): tool_call_id→阶段，旁路读原始事件（不入 ProjectedTurn），
  // 让运行中的工具（web_search）显示「正在检索/排队中/改用备用引擎」而非干等。已结束的工具自动清空。
  const toolPhases = useMemo(
    () => extractToolPhases(turn.events),
    [turn.events],
  );
  const workerToolPhases = useMemo(
    () => extractWorkerToolPhases(turn.events),
    [turn.events],
  );
  // 阻塞式求决策「待你拍板」: runId→escalation id from interactions[] (P3 · 按 id 精确提交).
  const pendingEscalations = useMemo(() => {
    const map = new Map<string, string>();
    for (const i of p.interactions) {
      if (i.kind === "escalation" && i.status === "pending") {
        map.set(i.runId, i.id);
      }
    }
    return map;
  }, [p.interactions]);
  // 队员工具明细 (RunDetail): runId→worker 工具调用 (旁路读原始事件，不入 ProjectedTurn)，喂给
  // 团队视图的队员详情面；实时与回放同一条接线（history 走 HistoryAssistant 里的同一提取器）。
  const runToolCalls = useMemo(
    () => extractRunToolCalls(turn.events),
    [turn.events],
  );
  // 两通道：调研回合台账（fold `#rN`）vs 辩论场级台账（extract `#eN`）。
  const turnEvidenceLedger = p.evidenceLedger;
  const debateEvidenceLedger = useMemo(
    () => extractEvidenceLedger(turn.events),
    [turn.events],
  );
  const graphAppendActKinds = useMemo(
    () => extractGraphAppendActKinds(turn.events),
    [turn.events],
  );
  const graphAppendAuthorizedBy = useMemo(
    () => extractGraphAppendAuthorizedBy(turn.events),
    [turn.events],
  );
  const turnQueued = useMemo(
    () => (live ? extractTurnQueued(turn.events) : null),
    [live, turn.events],
  );
  const meta = summarize(p);
  const isMulti = p.runs.length > 0;
  const team = isMulti
    ? {
        agents: p.agents,
        runs: p.runs,
        progress: p.progress,
        acts: p.acts,
        teamNotes: p.teamNotes,
        deliveryStatus: p.deliveryStatus,
        status: p.status,
        conversationId,
        pendingEscalations,
        escalationsInteractive: live,
        runToolCalls,
        workerToolPhases,
        evidenceLedger: debateEvidenceLedger,
      }
    : undefined;
  const empty =
    !isMulti && p.process.length === 0 && !p.content && !p.reasoning;
  // 对齐桌面：空正文 + error/unproductive → 可见失败说明（不必整泡无 process）。
  const failureNotice = !(p.content ?? "").trim()
    ? emptyFailureNotice(p.finishReason)
    : null;
  // 回合总账 — populated by message_end (null while streaming, so it appears on finish).
  // BYOK: billed total is 0; estimated_total may carry a community-catalog estimate.
  const turnMoney =
    p.cost && p.cost.total > 0
      ? { nano: p.cost.total, estimated: false }
      : p.cost?.estimated_total && p.cost.estimated_total > 0
        ? { nano: p.cost.estimated_total, estimated: true }
        : null;
  const cost = turnMoney
    ? formatCost(turnMoney.nano, turnMoney.estimated)
    : p.cost?.pricing_source === "unpriced"
      ? COST_UNPRICED_LABEL
      : null;
  const turnWarning = p.turnWarning;
  const supportIds: SupportDiagnosticIds = {
    conversationId,
    ...extractSupportIdsFromEvents(turn.events),
  };
  return (
    <div className="bubble assistant">
      {turnWarning && <div className="turn-warning">{turnWarning}</div>}
      {turnQueued && (
        <div className="finish-chip muted" data-testid="turn-queued-chip">
          排队中（第 {turnQueued.position} 位
          {turnQueued.queueDepth > 1 ? ` / 共 ${turnQueued.queueDepth} 条` : ""}
          ）
        </div>
      )}
      {empty && !failureNotice ? (
        <span className="muted">
          {live ? (turnQueued ? "等待上一回合结束…" : "…") : ""}
        </span>
      ) : !empty ? (
        <AssistantContent
          process={p.process}
          content={p.content}
          reasoning={p.reasoning}
          citations={p.citations}
          evidenceLedger={turnEvidenceLedger}
          captainContext={p.captainContext}
          team={team}
          debate={p.debate}
          debateRounds={p.debateRounds}
          debatePretrial={p.debatePretrial}
          asks={asks}
          escalationSlots={escalationSlots}
          hotTraces={hotTraces}
          stageCardTraces={stageCardTraces}
          toolPhases={toolPhases}
          graphAppendActKinds={graphAppendActKinds}
          graphAppendAuthorizedBy={graphAppendAuthorizedBy}
          onFill={onFill}
          supportIds={supportIds}
        />
      ) : null}
      {failureNotice && (
        <div className="error inline-actions">
          <span>{failureNotice}</span>
          <SupportDiagnosticCopyButton ids={supportIds} />
        </div>
      )}
      <FileArtifactsCard
        artifacts={artifacts}
        conversationId={conversationId}
      />
      {/* The team view carries its own progress header; the one-line meta is the
          single-agent fallback. */}
      {!isMulti && meta && <div className="meta">{meta}</div>}
      {cost && <div className="cost">{cost}</div>}
    </div>
  );
}

// A persisted assistant message, replayed through the SAME fold/rendering as a live turn:
// a multi-agent turn re-folds its run/tool journal (runs.events) into the team view, a
// single-agent tool turn restores its process timeline (runs.process), and the captain's
// reply / 思考 / 引用 come off the authoritative top-level fields. A row with nothing to
// show (a bare tool-only turn) renders nothing.
function HistoryAssistant({
  m,
  conversationId,
  onFill,
  onRetry,
  isLast,
}: {
  m: MessageDetail;
  conversationId: string | null;
  onFill: (text: string) => void;
  onRetry?: () => void;
  isLast?: boolean;
}) {
  const {
    team,
    debate,
    debateRounds,
    debatePretrial,
    turnWarning,
    foldEvidenceLedger,
    graphAppendActKinds,
    graphAppendAuthorizedBy,
    deliveryStatus,
  } = useMemo(() => {
    const events = m.runs?.events;
    const warning =
      m.runs?.turn_warning ??
      (events?.length ? extractTurnWarning(events) : null);
    if (!events || events.length === 0)
      return {
        team: undefined,
        debate: null,
        debateRounds: [] as DebateNarrativeRound[],
        debatePretrial: null,
        turnWarning: warning,
        foldEvidenceLedger: [],
        graphAppendActKinds: new Map<string, string>(),
        graphAppendAuthorizedBy: new Map<string, string>(),
        deliveryStatus: null,
      };
    const p = fold(events);
    const team =
      p.runs.length > 0
        ? {
            agents: p.agents,
            runs: p.runs,
            progress: p.progress,
            acts: p.acts,
            teamNotes: p.teamNotes,
            deliveryStatus: p.deliveryStatus,
            status: p.status,
            runToolCalls: extractRunToolCalls(events),
            // 辩论场级 `#eN`（勿写入 Message.evidence_ledger 语义）
            evidenceLedger: extractEvidenceLedger(events),
          }
        : undefined;
    return {
      team,
      debate: p.debate,
      debateRounds: p.debateRounds,
      debatePretrial: p.debatePretrial,
      turnWarning: warning ?? p.turnWarning,
      foldEvidenceLedger: p.evidenceLedger,
      graphAppendActKinds: extractGraphAppendActKinds(events),
      graphAppendAuthorizedBy: extractGraphAppendAuthorizedBy(events),
      deliveryStatus: p.deliveryStatus,
    };
  }, [m.runs]);
  const process = m.runs?.process ?? undefined;
  // 历史冷启动优先 REST `evidence_ledger`；缺列时回退 journal fold 的回合台账。
  const historyEvidenceLedger = m.evidenceLedger?.length
    ? m.evidenceLedger
    : foldEvidenceLedger;
  // 本回合产出文件：只认 delivery_status.artifacts（缺字段 → 空）。
  const artifacts = useMemo(
    () => resolveFileArtifactsForCard(deliveryStatus),
    [deliveryStatus],
  );
  // 非阻塞提问卡内容：仅多 Agent 历史持久化 runs.events（单聊为空 → 无卡，与桌面一致）。
  const asks = useMemo(() => extractAsks(m.runs?.events ?? []), [m.runs]);
  const escalationSlots = useMemo(
    () => extractEscalationSlots(m.runs?.events ?? []),
    [m.runs],
  );
  // 热审批/委派授权痕迹 (D3): 单聊审批回合的 events 也过 journal surface（二期），故历史可取。
  const hotTraces = useMemo(
    () => extractHotDecisionTraces(m.runs?.events ?? []),
    [m.runs],
  );
  const stageCardTraces = useMemo(
    () => extractStageCardTraces(m.runs?.events ?? []),
    [m.runs],
  );
  // P2：优先用 messages.cost 列（平台记账）；缺列或 BYOK 记账为 0 时 lazy-fetch 台账（含 estimated_cost）。
  const columnBilled =
    m.cost && m.cost.total > 0
      ? { nano: m.cost.total, estimated: false as const }
      : null;
  const { ref, money: lazyMoney } = useLazyMessageCost(
    columnBilled == null ? m.id : "",
  );
  const money = columnBilled ?? lazyMoney;
  const cost =
    money && money.nano > 0
      ? formatCost(money.nano, money.estimated)
      : m.cost?.pricing_source === "unpriced" || lazyMoney?.unpriced
        ? COST_UNPRICED_LABEL
        : null;
  const streaming = m.status === "running" && !m.paused;
  const interrupted =
    m.status === "incomplete" || m.runs?.finish_reason === "interrupted";
  const stopped = m.runs?.finish_reason === "cancelled";
  const emptyBody =
    !team &&
    (!process || process.length === 0) &&
    !m.content &&
    !m.reasoning_content &&
    m.citations.length === 0 &&
    artifacts.length === 0;
  const failureNotice =
    !streaming && !(m.content ?? "").trim()
      ? emptyFailureNotice(m.runs?.finish_reason)
      : null;
  const supportIds = historySupportIds(m, conversationId);

  if (
    emptyBody &&
    !turnWarning &&
    !interrupted &&
    !stopped &&
    !streaming &&
    !failureNotice
  ) {
    return null;
  }
  return (
    <div
      className="bubble assistant"
      ref={columnBilled == null ? ref : undefined}
    >
      {turnWarning && <div className="turn-warning">{turnWarning}</div>}
      {streaming && !m.content && !m.reasoning_content && !process?.length ? (
        <span className="muted">…</span>
      ) : emptyBody && failureNotice ? null : (
        <AssistantContent
          process={process}
          content={m.content ?? ""}
          reasoning={m.reasoning_content ?? undefined}
          citations={m.citations}
          evidenceLedger={historyEvidenceLedger}
          captainContext={m.runs?.captain_context ?? undefined}
          team={team}
          debate={debate}
          debateRounds={debateRounds}
          debatePretrial={debatePretrial}
          asks={asks}
          escalationSlots={escalationSlots}
          hotTraces={hotTraces}
          stageCardTraces={stageCardTraces}
          graphAppendActKinds={graphAppendActKinds}
          graphAppendAuthorizedBy={graphAppendAuthorizedBy}
          onFill={onFill}
          supportIds={supportIds}
        />
      )}
      {failureNotice && (
        <div className="error inline-actions">
          <span>{failureNotice}</span>
          <SupportDiagnosticCopyButton ids={supportIds} />
        </div>
      )}
      <FileArtifactsCard
        artifacts={artifacts}
        conversationId={conversationId}
      />
      {(interrupted || stopped) && isLast && onRetry && (
        <button type="button" className="retry-btn" onClick={onRetry}>
          重试
        </button>
      )}
      {cost && !streaming && <div className="cost">{cost}</div>}
    </div>
  );
}

export function ChatPage() {
  const navigate = useNavigate();
  const { id: conversationId } = useParams<{ id: string }>();
  // 历史对话抽屉 (☰): the chat is the landing surface now; history slides in over it.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [history, setHistory] = useState<MessageDetail[] | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  /** 诚实停止过渡：stopping 时 UI 不先于后端进终态；与 sending 合成 busy。 */
  const [stopPhase, setStopPhase] = useState<StopUiPhase>("idle");
  const [error, setError] = useState<ChatError | null>(null);
  /** Session permission recipe label (谨慎 / 少打断 / 托管 / 自定义). */
  const [permissionLabel, setPermissionLabel] = useState<string | null>(null);
  // 会话级模型组合 (对齐桌面): conversation override profile id (null = follow account default).
  // A draft seeds from last-used profile. Badge shows the combination name; tap opens picker.
  const [currentProfileId, setCurrentProfileId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const { data: modelProfiles } = useModelProfiles();
  // Files staged for the next send: their text rides the body (composer 附件). A pick that
  // can't be read as text (image / binary) surfaces `attachError` and isn't staged.
  const [attachments, setAttachments] = useState<MessageAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const attachInputRef = useRef<HTMLInputElement>(null);
  // The composer text input — focused after tapping a 下一步 chip so the user can edit/send.
  const composerInputRef = useRef<HTMLInputElement>(null);
  // Turns that paused at a checkpoint then lost their stream (durable resume frames),
  // surfaced as ResumeCards on reopen (结构化挂起 2b).
  const [paused, setPaused] = useState<PausedTurnSummary[]>([]);
  const [recoveredInteractions, setRecoveredInteractions] = useState<
    PendingInteractionSummary[]
  >([]);
  // Older messages exist above the loaded window (drives 加载更早); `loadingOlder` blocks
  // re-entrancy while a page is in flight (历史上翻分页).
  const [hasMoreBefore, setHasMoreBefore] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  // 「记忆已更新」卡 (③ §1.6): the latest window's offline-consolidation results, pinned at the
  // thread tail. Only the newest window carries them, so scroll-up (loadOlder) leaves them be.
  const [memoryUpdates, setMemoryUpdates] = useState<MemoryUpdate[]>([]);
  // Offline consolidation post-dates the turn — bump this gen to cancel in-flight polls on
  // conversation switch / unmount (mobile has no memory_updated firehose).
  const memoryPollGenRef = useRef(0);
  // REL-002: execution_completed → short-delay getMessages retries for harvest 终稿.
  // Cancel on conversation switch (leave/reopen still loads via the effect below).
  const harvestRefreshRef = useRef(
    createHarvestRefreshScheduler(async (cid, isCurrent) => {
      const {
        messages,
        hasMoreBefore: more,
        memoryUpdates: mem,
      } = await getMessages(cid);
      if (!isCurrent()) return;
      setHistory(messages);
      setHasMoreBefore(more);
      setMemoryUpdates(mem);
      setTurns((t) => dropSettledLiveTurns(t));
    }),
  );
  // The controller for the stream currently held open (send / reattach). Conversation
  // switch aborts it; 用户停止 does NOT — keep SSE until backend message_end (诚实过渡).
  const abortRef = useRef<AbortController | null>(null);
  /** Mid-flight（生成中再发）独立 AC；切会话时一并 abort。 */
  const midFlightAbortRef = useRef<AbortController | null>(null);
  /** 主路 SSE 是否仍在泵（供 mid-flight 等 drain 边界）。 */
  const primaryActiveRef = useRef(false);
  const primaryIdleWaitersRef = useRef<Array<() => void>>([]);
  /** 主路 + mid-flight 在途数；>0 则 sending。 */
  const inflightRef = useRef(0);
  const stopPhaseRef = useRef<StopUiPhase>("idle");
  const stopTimerRef = useRef(createStopConfirmTimer());

  const markStreamStart = () => {
    inflightRef.current += 1;
    setSending(true);
  };

  const markStreamEnd = () => {
    inflightRef.current = Math.max(0, inflightRef.current - 1);
    if (inflightRef.current === 0) setSending(false);
  };

  const signalPrimaryIdle = () => {
    primaryActiveRef.current = false;
    const waiters = primaryIdleWaitersRef.current.splice(0);
    for (const w of waiters) w();
  };

  const waitPrimaryIdle = () => {
    if (!primaryActiveRef.current) return Promise.resolve();
    return new Promise<void>((resolve) => {
      primaryIdleWaitersRef.current.push(resolve);
    });
  };

  const applyStopPhase = (phase: StopUiPhase) => {
    stopPhaseRef.current = phase;
    setStopPhase(phase);
  };

  /** Fresh read — avoids TS narrowing `stopPhaseRef.current` across awaits. */
  const isStoppingNow = (): boolean => stopPhaseRef.current === "stopping";

  const clearStopping = () => {
    stopTimerRef.current.clear();
    applyStopPhase("idle");
  };

  const busy = isStopBusy(sending, stopPhase);

  // Stick-to-bottom with upward-gesture detach + hysteresis (流式时上滑不强制贴底).
  // contentKey grows with the live tail so streaming tokens re-pin only while stuck.
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const lastHist =
    history && history.length > 0 ? history[history.length - 1] : null;
  const scrollContentKey = `${history?.length ?? 0}-${turns.length}-${lastTurn?.id ?? ""}-${lastTurn?.events.length ?? 0}-${lastHist?.id ?? ""}-${lastHist?.content?.length ?? 0}`;
  const { scrollRef, atBottom, jumpToBottom, preparePrepend, cancelPrepend } =
    useStickScroll(scrollContentKey, conversationId ?? null);

  // 语音输入 (桌面对齐)：转写文本追加到现有草稿 (不覆盖)，完成后聚焦输入框供编辑再发。
  // web 浏览器走 Web Speech API、原生壳走 capgo 插件，两者都不可用则 isSupported=false (按钮隐藏)。
  const voice = useVoiceInput({
    onTranscript: useCallback((text: string) => {
      setInput((prev) => (prev.trim() ? `${prev} ${text}` : text));
      requestAnimationFrame(() => composerInputRef.current?.focus());
    }, []),
  });

  // Append an event to the live (last) turn — lazily opening a userText-less turn when
  // none exists yet (a reattach on reopen, whose user bubble is already in history).
  const appendEvent = (event: SSEEvent) => {
    // 诚实停止：stopping 丢弃正文/工具突变，仍消费 run_* + 终态确认。
    if (
      stopPhaseRef.current === "stopping" &&
      !allowsEventWhileStopping(event.type)
    ) {
      return;
    }
    setTurns((t) => {
      if (t.length === 0) {
        return [{ id: crypto.randomUUID(), userText: null, events: [event] }];
      }
      const next = t.slice();
      const last = next[next.length - 1];
      next[next.length - 1] = { ...last, events: [...last.events, event] };
      return next;
    });
    if (stopPhaseRef.current === "stopping" && isStopConfirmEvent(event.type)) {
      clearStopping();
    }
    // 挂起即收口 (②): a live stream can END at a durable checkpoint — message_end carries
    // finish_reason=paused. The turn finalized (its in-process resolve Future was never
    // parked), so the live PauseCard no longer applies; re-read the recovery snapshot so
    // its durable ResumeCard surfaces once the stream settles (the single cold resume
    // path), exactly as a reopen would. One chokepoint for every stream
    // (send/resume/reconnect/attach), mirroring the desktop's message_end handler.
    if (conversationId && event.type === "message_end") {
      if ((event.payload as MessageEndPayload).finish_reason === "paused") {
        void refreshPaused(conversationId);
      }
      // 记忆更新可发现性: consolidation is offline/async — schedule delayed refreshes of
      // the thread-tail card so the user does not have to leave and reopen the chat.
      scheduleMemoryPoll(conversationId);
    }
    // REL-002: 后台执行终态 — fold no-op；经 getMessages 拉入 harvest 终稿（短延迟重试）。
    if (conversationId && event.type === "execution_completed") {
      harvestRefreshRef.current.schedule(conversationId);
    }
  };

  // Pull the latest window's memory_updates into the thread-tail card. Best-effort; a
  // failure must never disrupt the settled turn.
  async function refreshMemoryUpdates(cid: string) {
    try {
      const { memoryUpdates: next } = await getMessages(cid);
      setMemoryUpdates(next);
    } catch {
      /* ignore — poll is best-effort */
    }
  }

  // Delayed poll after message_end (2s / 8s / 20s). Always runs the full schedule so a
  // pre-existing card from an earlier turn does not abort before a fresh pass lands;
  // cancelled when the conversation changes (gen bump).
  function scheduleMemoryPoll(cid: string) {
    const gen = ++memoryPollGenRef.current;
    const delays = [2000, 8000, 20000];
    void (async () => {
      for (const ms of delays) {
        await new Promise((r) => setTimeout(r, ms));
        if (memoryPollGenRef.current !== gen) return;
        await refreshMemoryUpdates(cid);
        if (memoryPollGenRef.current !== gen) return;
      }
    })();
  }

  // Load the persisted transcript for the conversation in the URL — this is what makes a
  // refresh keep the conversation (刷新不丢): the id rides the route, the history is the
  // server's. Turns sent this session stream live below it (via the fold). If the latest
  // turn has no persisted reply (ends at a user message), a run may still be live
  // (执行与请求解耦 C1 · slice 1b): rejoin it and 续看 it finish.
  // biome-ignore lint/correctness/useExhaustiveDependencies: effect 按会话(conversationId/navigate)生命周期挂载重连 run；clearStopping 等仅作副作用调用，列入依赖会破坏重挂载语义
  useEffect(() => {
    // Cancel any in-flight memory-update polls / harvest refreshes from the previous conversation.
    memoryPollGenRef.current += 1;
    harvestRefreshRef.current.cancel();
    if (!conversationId) {
      // Draft (直接对话): no server conversation yet — ready to type, nothing to load.
      setHistory([]);
      setTurns([]);
      setError(null);
      setSending(false);
      clearStopping();
      setPaused([]);
      setHasMoreBefore(false);
      setMemoryUpdates([]);
      setPermissionLabel(null);
      // 新对话继承上次选择: seed the draft's profile from last-used (localStorage);
      // applied to the conversation on first send (startDraft).
      setCurrentProfileId(getLastModelProfileId());
      return;
    }
    setHistory(null);
    setTurns([]);
    setError(null);
    setSending(false);
    setPaused([]);
    setRecoveredInteractions([]);
    setHasMoreBefore(false);
    setMemoryUpdates([]);
    setPermissionLabel(null);
    setCurrentProfileId(null);
    let cancelled = false;
    void getConversation(conversationId)
      .then((c) => {
        if (cancelled) return;
        const axes = c.permission_axes;
        const host = axes?.host ?? "ask";
        const key = axes
          ? `${axes.file_write}/${axes.command}/${axes.team_kickoff}/${host}`
          : "session/auto/rules/ask";
        const labels: Record<string, string> = {
          "ask/ask/rules/off": "谨慎",
          "session/auto/rules/ask": "少打断",
          "session/auto/skip/session": "托管",
        };
        setPermissionLabel(labels[key] ?? "自定义");
        setCurrentProfileId(c.model_profile_id ?? null);
      })
      .catch(() => {
        /* best-effort */
      });
    // 统一恢复态快照（recovery 统一, 对称 §18.2）：一次属主校验读，既给出「待恢复」卡要用的挂起帧
    // （结构化挂起 2b），又给出「是否还有 detached live run 可续看」(slice 1b)。尽力而为，永不阻塞
    // 打开会话（失败 = 空快照，回合下次重开仍可恢复）。保留为 promise，让下方 attach 决策对齐同一
    // 份快照（与桌面端一致）。
    const recoveryLoaded = getRecovery(conversationId).catch(
      (): TurnRecovery => ({
        liveRunning: false,
        paused: [],
        pendingInteractions: [],
      }),
    );
    void recoveryLoaded.then((r) => {
      if (!cancelled) {
        setPaused(r.paused);
        setRecoveredInteractions(r.pendingInteractions);
      }
    });
    getMessages(conversationId)
      .then(async ({ messages, hasMoreBefore: more, memoryUpdates }) => {
        if (cancelled) return;
        setHistory(messages);
        setHasMoreBefore(more);
        // 「记忆已更新」卡 (③ §1.6): only the latest window carries them — pin at the thread
        // tail. A (re)open/refresh loads them; after message_end we also poll (no firehose),
        // and scroll-up (loadOlder) never overwrites them.
        setMemoryUpdates(memoryUpdates);
        // A draft's first message, handed off across the / → /c/:id remount: POST + stream
        // it now (the conversation exists but has no run yet, so attach would no-op).
        if (pendingFirstSend && pendingFirstSend.id === conversationId) {
          const p = pendingFirstSend;
          pendingFirstSend = null;
          void send({ text: p.text, attachments: p.attachments });
          return;
        }
        const last = messages[messages.length - 1];
        if (last && last.role === "user") {
          // 单一快照决定唯一可操作面：仅当有 detached live run 且无挂起帧时才 attach 续看。挂起即
          // 收口 (②)：到达 checkpoint 的回合已 FINALIZE（run 结束、落帧），是纯 durable——「待恢复」
          // 卡为唯一面，不再 attach（唯一的 live∩durable 重叠是 §六-1 薄网，帧没存住、paused 本就为
          // 空，进不到这支）。liveRunning 与 attach 端点同源活性判据 → 一次读即定面，liveRunning/
          // paused 不会互相矛盾（源头消除竞态，而非排序绕过）。
          const recovery = await recoveryLoaded;
          if (cancelled) return;
          if (recovery.liveRunning && recovery.paused.length === 0) {
            void attachOnOpen(conversationId);
          }
        } else if (
          last &&
          last.role === "assistant" &&
          last.status === "running"
        ) {
          // P4: overlay partial already painted; live → clear-then-fold rejoin;
          // dead lease ghost → interrupted affordance (no forever spinner).
          const recovery = await recoveryLoaded;
          if (cancelled) return;
          if (recovery.liveRunning && recovery.paused.length === 0) {
            void rejoinRunningHistory(conversationId);
          } else if (!recovery.liveRunning && recovery.paused.length === 0) {
            setHistory((h) => {
              if (!h || h.length === 0) return h;
              const next = h.slice();
              const i = next.length - 1;
              next[i] = {
                ...next[i],
                status: "incomplete",
                runs: {
                  events: next[i].runs?.events ?? [],
                  finish_reason: "interrupted",
                  process: next[i].runs?.process ?? null,
                  captain_context: next[i].runs?.captain_context,
                  turn_warning: next[i].runs?.turn_warning,
                },
              };
              return next;
            });
          }
        }
      })
      .catch((e) => {
        if (cancelled) return;
        if (!getTokens()) {
          navigate("/login", { replace: true });
          return;
        }
        setError({ text: e instanceof Error ? e.message : "加载消息失败" });
        setHistory([]);
      });
    // Switching conversation aborts any held stream so its events can't pollute the next
    // conversation's turns (shared state — turns aren't keyed by conversation). The server
    // run keeps going detached (slice 1a); reopening reattaches.
    return () => {
      cancelled = true;
      harvestRefreshRef.current.cancel();
      abortRef.current?.abort();
      midFlightAbortRef.current?.abort();
      clearStopping();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, navigate]);

  // Page strictly older messages in above the window (历史上翻分页). The oldest loaded
  // row's created_at is the cursor; we anchor the viewport (distance-from-bottom) so the
  // prepend doesn't yank the scroll. Re-entrancy-guarded; the chat keeps working if it fails.
  async function loadOlder() {
    if (!conversationId || loadingOlder || !hasMoreBefore) return;
    const oldest = history?.[0];
    if (!oldest) return;
    preparePrepend();
    setLoadingOlder(true);
    try {
      const { messages, hasMoreBefore: more } = await getMessages(
        conversationId,
        oldest.created_at,
      );
      setHistory((h) => [...messages, ...(h ?? [])]);
      setHasMoreBefore(more);
    } catch (e) {
      cancelPrepend();
      setError({
        text: e instanceof Error ? e.message : "加载更早消息失败",
      });
    } finally {
      setLoadingOlder(false);
    }
  }

  // The live turn's projection drives the interactive pause surface: while a stream is
  // held open (`busy`) and the fold reports a gate, the PauseCard below offers
  // resolution — equally for a fresh turn and one rejoined via reattach (a run paused at
  // an approval shows its live card on reconnect).
  const liveTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const liveProjection = useMemo(
    () => (liveTurn ? fold(liveTurn.events) : null),
    [liveTurn],
  );
  // 挂起即收口 (②, Phase 3): hot-path cards resolve live in-stream; cold path
  // (ask_user / plan_review / team_preview) finalizes and uses ResumeCard.
  const liveInteractions = busy
    ? (liveProjection?.interactions ?? []).filter((i) => i.status === "pending")
    : [];
  const liveApprovals = liveInteractions.filter(
    (i): i is Extract<ProjectedInteraction, { kind: "approval" }> =>
      i.kind === "approval",
  );
  const liveDelegations = liveInteractions.filter(
    (
      i,
    ): i is Extract<
      ProjectedInteraction,
      { kind: "delegation_authorization" }
    > => i.kind === "delegation_authorization",
  );
  const approvalCards =
    liveApprovals.length > 0
      ? liveApprovals
      : recoveredInteractions
          .map(recoveredApprovalPending)
          .filter((x): x is NonNullable<typeof x> => x != null);
  const delegationCards =
    liveDelegations.length > 0
      ? liveDelegations
      : recoveredInteractions
          .map(recoveredDelegation)
          .filter((x): x is NonNullable<typeof x> => x != null);

  // 阶段推进卡（批 B）：幕 1 收尾后耐久展示；live fold 优先，冷开走 recovery。
  const stageCards = useMemo(() => {
    const fromLive = (liveProjection?.interactions ?? []).filter(
      (i): i is Extract<ProjectedInteraction, { kind: "stage_card" }> =>
        i.kind === "stage_card" &&
        (i.status === "pending" || i.status === "orphaned"),
    );
    if (fromLive.length > 0) return fromLive;
    if (busy) return [];
    return recoveredInteractions
      .map(recoveredStageCard)
      .filter((x): x is NonNullable<typeof x> => x != null);
  }, [liveProjection, recoveredInteractions, busy]);

  // 下一步推荐 chips: live path matches followups_generated.message_id to this turn's
  // message_start; reload (no live turn) replays MessageDetail.followups on the latest
  // finished assistant. Retire when the next turn starts (`busy`).
  const followups = useMemo(() => {
    if (busy) return [];
    if (liveTurn) return extractFollowups(liveTurn.events);
    const last =
      history && history.length > 0 ? history[history.length - 1] : null;
    if (
      last?.role === "assistant" &&
      last.followups &&
      last.followups.length > 0
    ) {
      return last.followups;
    }
    return [];
  }, [busy, liveTurn, history]);

  const followupsUnavailable = useMemo(() => {
    if (busy || followups.length > 0) return false;
    if (liveTurn) return extractFollowupsUnavailable(liveTurn.events);
    return false;
  }, [busy, liveTurn, followups.length]);

  // Stage picked files as text attachments (composer 附件). Each is read on the spot (the
  // pick is the grant); images / binaries are refused with a reason and skipped. The input
  // is reset so re-picking the same file fires onChange again.
  async function onPickFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    setAttachError(null);
    const added: MessageAttachment[] = [];
    const refused: string[] = [];
    for (const file of files) {
      const res = await readTextAttachment(file);
      if (res.ok) added.push(res.attachment);
      else refused.push(`${file.name}：${res.reason}`);
    }
    if (added.length > 0) setAttachments((prev) => [...prev, ...added]);
    if (refused.length > 0) setAttachError(refused.join("；"));
  }

  function removeAttachment(name: string) {
    setAttachments((prev) => prev.filter((a) => a.name !== name));
  }

  // Tap a 下一步 chip → fill the composer (don't auto-send: let the user edit first, like
  // desktop). Appends after a space when text is already typed, so a chip never clobbers it.
  function fillFollowup(text: string) {
    setInput((prev) => (prev.trim() ? `${prev} ${text}` : text));
    composerInputRef.current?.focus();
  }

  // 会话级模型组合: apply a profile from the ModelPicker. A concrete id is remembered as
  // last-used; clearing (跟随账号默认) forgets it. An open conversation is PATCHed now;
  // a draft just holds it locally until startDraft applies it.
  async function onSelectProfile(profileId: string | null) {
    setPickerOpen(false);
    if (profileId) setLastModelProfileId(profileId);
    else clearLastModelProfileId();
    if (!conversationId) {
      setCurrentProfileId(profileId);
      return;
    }
    const previous = currentProfileId;
    setCurrentProfileId(profileId);
    try {
      const updated = await setConversationModelProfile(
        conversationId,
        profileId,
      );
      setCurrentProfileId(updated.model_profile_id ?? null);
    } catch (e) {
      setCurrentProfileId(previous);
      setError({ text: e instanceof Error ? e.message : "切换模型组合失败" });
    }
  }

  // 直接对话: a draft (no conversationId) lazily creates a conversation on first send, then
  // routes to /c/:id where the remounted page POST+streams the message (via pendingFirstSend).
  // Keeps the empty-shell-conversation cost off「新建」— the row only exists once you commit.
  async function startDraft() {
    const text = input.trim();
    if (!text || conversationId || busy) return;
    const outgoing = attachments;
    setError(null);
    setSending(true);
    try {
      const id = await createConversation();
      // 新对话继承上次选择: apply the draft's chosen profile before its first turn streams
      // (best-effort — a failure just falls back to the account default).
      if (currentProfileId) {
        try {
          await setConversationModelProfile(id, currentProfileId);
        } catch {
          /* non-fatal: the first turn runs on the account default */
        }
      }
      pendingFirstSend = { id, text, attachments: outgoing };
      setInput("");
      setAttachments([]);
      setAttachError(null);
      navigate(`/c/${id}`, { replace: true });
    } catch (e) {
      setError({ text: e instanceof Error ? e.message : "创建会话失败" });
      setSending(false);
    }
  }

  // Submit dispatch: a draft creates-then-routes (startDraft); an open conversation streams
  // in place (send). The composer / Enter both go through here.
  const onSubmit = () => {
    if (conversationId) void send();
    else void startDraft();
  };

  // Stream a turn into the open conversation. `override` carries a draft's first message
  // across the remount (it bypasses the input state, which the new page doesn't have).
  // 生成中再发走 mid-flight（turn_queued / user_interjection），composer 不禁发。
  async function send(override?: {
    text: string;
    attachments: MessageAttachment[];
  }) {
    const text = (override?.text ?? input).trim();
    if (!text || !conversationId) return;
    if (stopPhaseRef.current === "stopping") return;
    // Interactive mid-flight while a turn is already streaming.
    if (!override && sending) {
      void sendWhileBusy(text);
      return;
    }
    const outgoing = override?.attachments ?? attachments;
    if (!override) {
      setInput("");
      setAttachments([]);
    }
    setAttachError(null);
    setError(null);
    clearStopping();
    markStreamStart();
    primaryActiveRef.current = true;
    jumpToBottom();
    setTurns((t) => [
      ...t,
      {
        id: crypto.randomUUID(),
        userText: text,
        events: [],
        attachments: outgoing.map((a) => ({
          name: a.name,
          truncated: a.truncated,
        })),
      },
    ]);

    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamMessage(
        conversationId,
        text,
        appendEvent,
        ac.signal,
        outgoing.length > 0 ? outgoing : undefined,
      );
    } catch (e) {
      if (isAbort(e)) return; // conversation switch — partial stays, server salvages
      // Pre-stream refusal (402 LLM_KEY_REQUIRED etc.) — surface banner +「去配置」, do not
      // treat as a dropped live run (nothing started).
      if (e instanceof StreamHttpError) {
        const d = describeStreamHttpError(e);
        setError({
          text: d.message,
          action: d.action ?? undefined,
        });
        return;
      }
      // 诚实停止等待中断流：不自动重连，保持 stopping + 未确认可重试。
      if (isStoppingNow()) return;
      // A mid-stream drop no longer means the turn died (slice 1a: it runs detached) —
      // rejoin it (1b) rather than resending, which would double-run it.
      await reconnect();
    } finally {
      signalPrimaryIdle();
      // Only settle sending if still the current op — a switch / takeover (reconnect /
      // mid-flight turn2) replaced the controller and owns the state now.
      if (abortRef.current === ac) {
        abortRef.current = null;
        markStreamEnd();
      } else {
        inflightRef.current = Math.max(0, inflightRef.current - 1);
      }
    }
  }

  /** 生成中发送：独立 POST SSE，先呈现 turn_queued，主路空闲后再开 turn2。 */
  async function sendWhileBusy(text: string) {
    if (!conversationId) return;
    const outgoing = attachments;
    setInput("");
    setAttachments([]);
    setAttachError(null);
    setError(null);
    jumpToBottom();
    markStreamStart();

    const ac = new AbortController();
    midFlightAbortRef.current = ac;
    try {
      const result = await sendMidFlightMessage(
        conversationId,
        text,
        {
          onLiveEvent: appendEvent,
          beginTurn2: () => {
            setTurns((t) => [
              ...t,
              {
                id: crypto.randomUUID(),
                userText: text,
                events: [],
                attachments: outgoing.map((a) => ({
                  name: a.name,
                  truncated: a.truncated,
                })),
              },
            ]);
            abortRef.current = ac;
          },
          onTurn2Event: appendEvent,
          isPrimaryIdle: () => !primaryActiveRef.current,
          waitPrimaryIdle,
        },
        outgoing.length > 0 ? outgoing : undefined,
        ac.signal,
      );
      if (result.kind === "blocked") {
        setError({ text: result.message ?? "请先处理待确认事项" });
      } else if (result.kind === "error") {
        setError({ text: result.message });
      }
    } finally {
      if (midFlightAbortRef.current === ac) {
        midFlightAbortRef.current = null;
      }
      if (abortRef.current === ac) {
        abortRef.current = null;
      }
      markStreamEnd();
    }
  }

  // 诚实停止闭环：进入「停止中」可见态，POST /stop，保持 SSE 等后端终态（不本地 abort /
  // 不伪造终态）。失败或宽限未确认 → 可见并可重试。
  function stop() {
    if (!busy && stopPhaseRef.current !== "stopping") return;
    if (!conversationId) {
      // Draft edge: no server run yet — local abort only.
      abortRef.current?.abort();
      return;
    }
    setError(null);
    applyStopPhase(reduceStopPhase(stopPhaseRef.current, "request_stop"));
    stopTimerRef.current.arm(() => {
      if (stopPhaseRef.current !== "stopping") return;
      setError({
        text: STOP_UNCONFIRMED_MESSAGE,
        retryStop: true,
      });
    });
    void stopConversation(conversationId)
      .then(() => {
        if (stopPhaseRef.current === "stopping") {
          setError((e) => (e?.retryStop ? null : e));
        }
      })
      .catch(() => {
        if (stopPhaseRef.current !== "stopping") return;
        stopTimerRef.current.clear();
        applyStopPhase(reduceStopPhase("stopping", "stop_http_fail"));
        setError({
          text: STOP_FAILED_MESSAGE,
          retryStop: true,
        });
      });
  }

  // Rejoin a turn whose live stream dropped mid-flight (实时重连续看 C1 · slice 1b). Resets
  // the partial bubble (the replay re-sends the full transcript-so-far) then attaches:
  // replay + live tail. On "none" the detached run already finished — reload the persisted
  // transcript so the live turn is replaced by its saved reply. A second drop offers a
  // manual 重连.
  async function reconnect() {
    if (!conversationId) return;
    setError(null);
    clearStopping();
    setSending(true);
    setTurns((t) => {
      if (t.length === 0) return t;
      const next = t.slice();
      next[next.length - 1] = { ...next[next.length - 1], events: [] };
      return next;
    });
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const outcome = await attachStream(
        conversationId,
        appendEvent,
        ac.signal,
      );
      if (outcome === "none" && abortRef.current === ac) {
        setTurns((t) => t.slice(0, -1));
        const {
          messages,
          hasMoreBefore: more,
          memoryUpdates: mem,
        } = await getMessages(conversationId);
        if (abortRef.current === ac) {
          setHistory(messages);
          setHasMoreBefore(more);
          setMemoryUpdates(mem);
        }
      }
    } catch (e) {
      if (isAbort(e)) return;
      if (stopPhaseRef.current === "stopping") return;
      setError({ text: RECONNECT_BANNER, reconnect: true });
    } finally {
      if (abortRef.current === ac) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  // P4: interrupted salvage → regenerate from the preceding user message (same endpoint
  // as desktop runRegenerate; no new API).
  async function retryInterrupted() {
    if (!conversationId || !history || busy) return;
    const last = history[history.length - 1];
    if (!last || last.role !== "assistant") return;
    let userId: string | null = null;
    for (let i = history.length - 2; i >= 0; i--) {
      if (history[i].role === "user") {
        userId = history[i].id;
        break;
      }
    }
    if (!userId) return;
    setError(null);
    clearStopping();
    setSending(true);
    // Drop interrupted assistant from history; live turn carries the regenerate stream.
    setHistory((h) => (h ? h.slice(0, -1) : h));
    setTurns([
      {
        id: crypto.randomUUID(),
        userText: null,
        events: [],
      },
    ]);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await regenerateStream(conversationId, userId, appendEvent, ac.signal);
    } catch (e) {
      if (isAbort(e)) return;
      if (e instanceof StreamHttpError) {
        const d = describeStreamHttpError(e);
        setError({
          text: d.message,
          action: d.action ?? undefined,
        });
        return;
      }
      setError({ text: e instanceof Error ? e.message : "重试失败" });
    } finally {
      if (abortRef.current === ac) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  // On reopen, rejoin a run that may still be live for the latest (reply-less) turn. Unlike
  // reconnect there is no partial bubble to reset — the reopened transcript ends at the
  // user message; appendEvent lazily opens the assistant bubble, so a 204 (nothing live)
  // is a clean no-op with no flicker. Identity-guarded (`abortRef.current === ac`) so a
  // conversation switch / takeover never lets this stale op clobber the next view.
  async function attachOnOpen(cid: string) {
    setSending(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const outcome = await attachStream(cid, appendEvent, ac.signal);
      if (outcome === "none" && abortRef.current === ac) {
        // Finished / never ran / suspended — reload to catch a reply that landed between
        // the history load and the attach (a suspended turn surfaces via durable resume).
        const {
          messages,
          hasMoreBefore: more,
          memoryUpdates: mem,
        } = await getMessages(cid);
        if (abortRef.current === ac) {
          setHistory(messages);
          setHasMoreBefore(more);
          setMemoryUpdates(mem);
        }
      }
    } catch (e) {
      if (isAbort(e)) return;
      if (stopPhaseRef.current === "stopping") return;
      setError({ text: RECONNECT_BANNER, reconnect: true });
    } finally {
      if (abortRef.current === ac) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  // P4 clear-then-fold: history already shows a running overlay partial — drop it so the
  // full journal replay does not double-fold tools/content, then attach live.
  async function rejoinRunningHistory(cid: string) {
    setError(null);
    setSending(true);
    setHistory((h) => {
      if (!h || h.length === 0) return h;
      const last = h[h.length - 1];
      if (last.role === "assistant") return h.slice(0, -1);
      return h;
    });
    setTurns([]);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const outcome = await attachStream(cid, appendEvent, ac.signal);
      if (outcome === "none" && abortRef.current === ac) {
        const {
          messages,
          hasMoreBefore: more,
          memoryUpdates: mem,
        } = await getMessages(cid);
        if (abortRef.current === ac) {
          setHistory(messages);
          setHasMoreBefore(more);
          setMemoryUpdates(mem);
        }
      }
    } catch (e) {
      if (isAbort(e)) return;
      if (stopPhaseRef.current === "stopping") return;
      setError({ text: RECONNECT_BANNER, reconnect: true });
    } finally {
      if (abortRef.current === ac) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  // 挂起即收口 (②): re-read the conversation's recovery snapshot — used when a live stream
  // ends at a checkpoint (appendEvent sees message_end finish_reason=paused) so the just-
  // finalized turn's durable ResumeCard surfaces (it renders once `sending` flips false).
  // Cheap + idempotent; best-effort — a recovery hiccup must never disrupt the settled turn.
  async function refreshPaused(cid: string) {
    try {
      const r = await getRecovery(cid);
      setPaused(r.paused);
    } catch {
      /* best-effort: never break the just-finished turn on a recovery refresh */
    }
  }

  // Continue a durably-paused turn (结构化挂起 2b). The user's decision is POSTed to the
  // resume endpoint, which claims the persisted frame (atomic — a stale double-tap 404s)
  // and drives the rest of the turn on a fresh SSE; we stream it into a userText-less turn
  // (the paused turn's user bubble is already in history). The card is dropped
  // optimistically; a mid-stream drop rejoins the now-live run rather than re-resuming.
  async function resume(
    messageId: string,
    decision: CheckpointDecision,
    note: string,
    selected: string[] = [],
    styleId: string | null = null,
    formatId: string | null = null,
  ) {
    if (!conversationId || busy) return;
    setPaused((p) => p.filter((x) => x.message_id !== messageId));
    setError(null);
    clearStopping();
    setSending(true);
    setTurns((t) => [
      ...t,
      { id: crypto.randomUUID(), userText: null, events: [] },
    ]);

    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await resumeStream(
        conversationId,
        messageId,
        {
          decision,
          note,
          selected,
          ...(styleId ? { style_id: styleId } : {}),
          ...(formatId ? { format_id: formatId } : {}),
        },
        appendEvent,
        ac.signal,
      );
    } catch (e) {
      if (isAbort(e)) return;
      if (stopPhaseRef.current === "stopping") return;
      await reconnect();
    } finally {
      if (abortRef.current === ac) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  /** 推进卡 resolve：起新回合 SSE（机制直起辩论或回灌调研）。 */
  async function runStageCard(
    stageCardId: string,
    body: {
      decision: "start_debate" | "research_first";
      note?: string;
      motionOverride?: string | null;
    },
    onEvent: (event: SSEEvent) => void,
  ): Promise<void> {
    if (!conversationId || busy) return;
    setRecoveredInteractions((prev) =>
      prev.filter((a) => a.id !== stageCardId),
    );
    setError(null);
    clearStopping();
    setSending(true);
    setTurns((t) => [
      ...t,
      { id: crypto.randomUUID(), userText: null, events: [] },
    ]);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await resolveStageCardStream(
        conversationId,
        stageCardId,
        body,
        onEvent,
        ac.signal,
      );
    } catch (e) {
      if (isAbort(e)) return;
      if (e instanceof StreamHttpError && e.status === 422) {
        // 检定失败：撤回空回合，卡保持 pending（inline 报错由 StageCard 承接）
        setTurns((t) => (t.length > 0 ? t.slice(0, -1) : t));
        setSending(false);
        abortRef.current = null;
        throw e;
      }
      if (stopPhaseRef.current === "stopping") return;
      await reconnect();
    } finally {
      if (abortRef.current === ac) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  // 当前组合 badge: conversation override → account default → placeholder.
  const modelLabel =
    profileDisplayLabel(modelProfiles, currentProfileId) ?? "默认组合";

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link icon-btn"
          aria-label="对话历史"
          onClick={() => setDrawerOpen(true)}
        >
          <Menu size={20} />
        </button>
        <span className="bar-title">
          {conversationId ? "对话" : "新对话"}
          {permissionLabel ? (
            <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
              · {permissionLabel}
            </span>
          ) : null}
        </span>
        <div className="bar-right">
          {conversationId && (
            <button
              type="button"
              className="link icon-btn"
              aria-label="文件"
              onClick={() => navigate(`/c/${conversationId}/files`)}
            >
              <Folder size={20} />
            </button>
          )}
          <button
            type="button"
            className="link icon-btn"
            aria-label="新对话"
            onClick={() => navigate("/")}
          >
            <SquarePen size={20} />
          </button>
        </div>
      </header>

      <div className="messages-pane">
        <div className="messages" ref={scrollRef}>
          {history === null && !error && <p className="muted hint">加载中…</p>}
          {history !== null &&
            history.length === 0 &&
            turns.length === 0 &&
            !error &&
            (() => {
              // 平台代付、开箱即用：无「先接入模型」门，keyless 直接进欢迎态。
              if (conversationId) {
                return <p className="muted hint">发一条消息开始对话。</p>;
              }
              const copy = emptyChatCopy();
              return (
                <div className="chat-welcome">
                  <div className="chat-welcome-title">{copy.title}</div>
                  <div className="chat-welcome-sub">{copy.subtitle}</div>
                </div>
              );
            })()}
          {hasMoreBefore && (
            <button
              type="button"
              className="load-older"
              onClick={() => void loadOlder()}
              disabled={loadingOlder}
            >
              {loadingOlder ? "加载中…" : "加载更早的消息"}
            </button>
          )}
          {history?.map((m, i) => {
            if (m.role !== "user")
              return (
                <HistoryAssistant
                  key={m.id}
                  m={m}
                  conversationId={conversationId ?? null}
                  onFill={fillFollowup}
                  isLast={i === history.length - 1 && turns.length === 0}
                  onRetry={
                    i === history.length - 1 && turns.length === 0
                      ? () => void retryInterrupted()
                      : undefined
                  }
                />
              );
            const atts = m.attachments ?? [];
            if (!m.content && atts.length === 0) return null;
            // 异步团队收口：优先 REST origin；正文前缀兜底旧数据
            if (
              m.role === "user" &&
              (m.origin === "execution_harvest" ||
                (typeof m.content === "string" &&
                  m.content.startsWith("【系统收口】")))
            ) {
              return (
                <div
                  key={m.id}
                  className="system-chip"
                  data-testid="harvest-system-chip"
                >
                  后台团队已完成，系统自动收口
                </div>
              );
            }
            return (
              <div key={m.id} className="bubble user">
                {m.content}
                <AttachmentChips items={atts} />
              </div>
            );
          })}
          {turns.map((turn, i) => (
            <div key={turn.id} className="turn">
              {turn.userText !== null && (
                <div className="bubble user">
                  {turn.userText}
                  <AttachmentChips items={turn.attachments ?? []} />
                </div>
              )}
              <AssistantBubble
                turn={turn}
                live={busy && i === turns.length - 1}
                conversationId={conversationId ?? null}
                onFill={fillFollowup}
              />
            </div>
          ))}
          {/* 「记忆已更新」卡 (③ §1.6): offline-consolidation results pinned at the thread tail
              — it post-dates every turn (consolidation folds a window of finished turns). The
              card filters empty updates itself, so the common (none) case renders nothing. */}
          <MemoryUpdateCard updates={memoryUpdates} />
        </div>
        {!atBottom && (history?.length || turns.length) ? (
          <button
            type="button"
            className="jump-bottom"
            onClick={jumpToBottom}
            aria-label="回到底部"
          >
            <ArrowDown size={14} aria-hidden />
            回到底部
          </button>
        ) : null}
      </div>

      {approvalCards.map((pending) =>
        conversationId ? (
          <PauseCard
            key={pending.id}
            pending={pending}
            conversationId={conversationId}
            onResolved={() =>
              setRecoveredInteractions((prev) =>
                prev.filter((a) => a.id !== pending.id),
              )
            }
          />
        ) : null,
      )}
      {delegationCards.map((pending) =>
        conversationId ? (
          <DelegationAuthorizationCard
            key={pending.id}
            pending={pending}
            conversationId={conversationId}
            onResolved={() =>
              setRecoveredInteractions((prev) =>
                prev.filter((a) => a.id !== pending.id),
              )
            }
          />
        ) : null,
      )}

      {/* Durable resume cards (a turn that paused then lost its stream). Hidden while a
          stream is live — a live run owns the pause surface (PauseCard) instead. */}
      {!busy &&
        paused.map((p) => (
          <ResumeCard
            key={p.message_id}
            paused={p}
            onResume={(decision, note, selected, styleId, formatId) =>
              void resume(
                p.message_id,
                decision,
                note,
                selected,
                styleId ?? null,
                formatId ?? null,
              )
            }
          />
        ))}

      {!busy &&
        conversationId &&
        stageCards.map((card) => (
          <StageCard
            key={card.id}
            card={card}
            onResolve={async (args) => {
              await runStageCard(card.id, args, appendEvent);
            }}
          />
        ))}

      {error && (
        <div className="error bar">
          <span>{error.text}</span>
          <div className="error-bar-actions">
            {conversationId && (
              <SupportDiagnosticCopyButton ids={{ conversationId }} />
            )}
            {error.action && (
              <button
                type="button"
                className="link config-action"
                onClick={() => {
                  const href = error.action?.href;
                  if (!href) return;
                  setError(null);
                  navigate(href);
                }}
              >
                {error.action.label}
              </button>
            )}
            {error.reconnect && (
              <button
                type="button"
                className="link reconnect"
                onClick={() => void reconnect()}
              >
                重连
              </button>
            )}
            {error.retryStop && (
              <button
                type="button"
                className="link reconnect"
                onClick={() => stop()}
              >
                {STOP_RETRY_LABEL}
              </button>
            )}
          </div>
        </div>
      )}

      {attachError && (
        <div className="error bar">
          <span>{attachError}</span>
        </div>
      )}

      {(followups.length > 0 || followupsUnavailable) && (
        <div className="followups">
          <div className="followups-label">
            <Sparkles size={12} />
            <span>下一步</span>
          </div>
          {followups.length === 0 ? (
            <div className="followups-empty muted">推荐暂时不可用</div>
          ) : (
            <div className="followups-row">
              {followups.map((text) => (
                <button
                  key={text}
                  type="button"
                  className="followup-chip"
                  onClick={() => fillFollowup(text)}
                >
                  {text}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {attachments.length > 0 && (
        <div className="attach-tray">
          {attachments.map((a) => (
            <span key={a.name} className="attach-chip">
              <span aria-hidden>📎</span>
              <span className="attach-chip-name">{a.name}</span>
              {a.truncated && <span className="attach-chip-trunc">已截断</span>}
              <button
                type="button"
                className="attach-chip-x"
                onClick={() => removeAttachment(a.name)}
                aria-label="移除附件"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {voice.error && (
        <div className="error bar">
          <span>{voice.error}</span>
          <button type="button" className="link" onClick={voice.dismissError}>
            知道了
          </button>
        </div>
      )}

      {voice.isRecording && (
        <VoiceRecordingBar
          duration={voice.duration}
          interimText={voice.interimText}
          onCancel={voice.cancel}
        />
      )}

      <div className="model-bar">
        <button
          type="button"
          className="model-badge"
          onClick={() => setPickerOpen(true)}
          disabled={history === null || busy}
          aria-label={`当前模型组合：${modelLabel}，点击切换`}
        >
          <Bot size={14} aria-hidden />
          <span className="model-badge-name">{modelLabel}</span>
        </button>
      </div>

      <div className="composer">
        <input
          ref={attachInputRef}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={(e) => void onPickFiles(e)}
        />
        <button
          type="button"
          className="attach-btn"
          onClick={() => attachInputRef.current?.click()}
          disabled={history === null || stopPhase === "stopping"}
          aria-label="添加附件"
        >
          ＋
        </button>
        <input
          ref={composerInputRef}
          placeholder={history === null ? "加载中…" : "说点什么…"}
          value={input}
          disabled={history === null || stopPhase === "stopping"}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSubmit();
          }}
        />
        {voice.isSupported && (
          <VoiceButton
            state={voice.state}
            disabled={history === null || stopPhase === "stopping"}
            onClick={voice.toggle}
          />
        )}
        {busy ? (
          <>
            <button
              type="button"
              className="send-btn"
              onClick={() => void onSubmit()}
              disabled={
                history === null || !input.trim() || stopPhase === "stopping"
              }
              aria-label="发送插话"
              title="发送插话"
            >
              <Send size={18} aria-hidden />
            </button>
            <button
              type="button"
              className={`stop${stopPhase === "stopping" ? " stopping" : ""}`}
              onClick={stop}
              aria-label={stopButtonLabel(stopPhase)}
              title={stopButtonLabel(stopPhase)}
              aria-busy={stopPhase === "stopping"}
            >
              {stopPhase === "stopping" ? (
                <Loader2 size={18} className="voice-spin" aria-hidden />
              ) : (
                <Square size={16} aria-hidden />
              )}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="send-btn"
            onClick={() => void onSubmit()}
            disabled={history === null || !input.trim()}
            aria-label="发送"
            title="发送"
          >
            <Send size={18} aria-hidden />
          </button>
        )}
      </div>

      {pickerOpen && (
        <ModelPicker
          conversationProfileId={currentProfileId}
          onSelect={(id) => void onSelectProfile(id)}
          onClose={() => setPickerOpen(false)}
        />
      )}

      <ConversationDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onOpen={() => setDrawerOpen(true)}
        activeId={conversationId}
      />
    </div>
  );
}
