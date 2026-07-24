import {
  EXECUTION_HARVEST_ORIGIN,
  isExecutionHarvestMessage,
} from "@/lib/executionHarvest";
import { ensureTimelineMarkersFromJournal } from "@/lib/foldMessageLane";
import { api } from "@/services/api";
import { surfaceResumeFromAssistant } from "@/services/resume";
import {
  type MemoryUpdate,
  type Message,
  getRuntime,
  useConversationStore,
} from "@/stores/conversation";
import { hydrateInteractionsFromJournal } from "@/stores/interactions";
import type { components } from "@/types/api.generated";
import type {
  ContextBlockWire,
  ProcessStep,
  SSEEvent,
  UsageBreakdown,
} from "@/types/events";

type Schemas = components["schemas"];
/** A window of messages (cursor-windowed, oldest-first) from the REST endpoint. */
type BackendMessageListResponse = Schemas["MessageListResponse"];

/**
 * A persisted message as the REST endpoint shapes it. Mirrors the generated
 * `MessageDetail`, but types `runs.events` as the client's {@link SSEEvent}
 * union (the OpenAPI carries it as opaque JSON — SSE/event payloads are exempt
 * from the generated-types rule, API 开发规范) so the team-graph replay fold is
 * typed end to end.
 */
export interface BackendMessage {
  id: string;
  conversation_id: string;
  role: string;
  content: string | null;
  reasoning_content: string | null;
  /** The turn's log correlation id (messages.trace_id) — replayed onto
   * `message.traceId` so a reloaded bubble can copy it for one-step log lookup. */
  trace_id?: string | null;
  attachments?: {
    name: string;
    path: string;
    truncated: boolean;
    kind?: "file" | "dir" | "conversation";
    workspace_path?: string | null;
    conversation_id?: string | null;
  }[];
  citations?: {
    url: string;
    title: string;
    snippet?: string;
    site?: string;
    id?: string | null;
    date?: string | null;
    tier?: string | null;
    query?: string | null;
    deep_read?: boolean | null;
    registrant?: string | null;
    citable?: boolean | null;
  }[];
  /** 回合调研台账（引用即出处 P1, DERIVED）：messages.evidence_ledger。 */
  evidence_ledger?: {
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
  }[];
  /** 下一步推荐 chips (下一步推荐, DERIVED 持久化): the assistant row's persisted quick-reply
   * suggestions (messages.followups column, twin of the title). Replayed onto
   * `message.followups` so reopening a conversation shows the last turn's chips again — live
   * they rode `followups_generated`. Empty [] for user / none-minted turns. */
  followups?: string[];
  /** 回复反馈 (点赞/点踩, 对话基础功能补齐): the user's rating on this assistant reply
   * (messages.feedback column) — "up" | "down" | null(未评价). Replayed onto
   * `message.feedback` so a reloaded bubble shows the rating the user gave. */
  feedback?: "up" | "down" | null;
  /** Persisted turn replay payload. `events` is a multi-agent turn's ordered
   * run/tool SSE events (replayed through the same fold as the live stream to
   * rebuild the team graph on reload, §9.3); `process` is a single-agent turn's
   * 思考·正文·工具 inline timeline (前端UX设计.md §一B). `run_processes` is the
   * per-worker-run timeline map (对称 CEO process). null for user / plain turns. (Opaque JSON
   * in the OpenAPI — SSE/event payloads are exempt from the generated-types rule.) */
  runs?: {
    events: SSEEvent[];
    finish_reason: string | null;
    process?: ProcessStep[] | null;
    /** Per-run ProcessStep[] (run_id → steps); reload seeds run detail timelines. */
    run_processes?: Record<string, ProcessStep[]> | null;
    /** 收到的上下文 · CEO 侧 (上下文传递可视化 通道①): the captain's `run_context` blocks,
     * persisted turn-level (the captain is the bubble above the graph, present even in pure
     * chat where `events` is empty). Replayed onto `message.captainContext` on reload. */
    captain_context?: ContextBlockWire[] | null;
    /** 报错回合's terminal error (Tier 2 a): projected from the journal's `turn_end` outcome
     * fact so the inline error card replays on reload (live, the error rode a transport-only
     * `error` SSE event). Replayed onto `message.error` — same `{code, message}` shape the
     * live handler attaches. null for a clean turn. */
    error?: { code: string; message: string } | null;
    /** 预检警告（P2 DURABLE）：journaled turn_warning lifted for plain-chat reload. */
    turn_warning?: string | null;
  } | null;
  /** 回合 token 用量 (Tier 2 重载持久化): the turn's token snapshot in the ledger short-key
   * shape, projected server-side from the row's `usage` column. Replayed onto
   * `message.usage` so the bubble's meta row caption replays on reload — live, it rode
   * `message_end`. null for user rows and no-spend (errored/empty) turns. */
  usage?: UsageBreakdown | null;
  /** Progressive assistant-row lifecycle (``usage.status``). Overlay / salvage
   * criterion — ``running`` hydrates as streaming partial; ``incomplete`` as
   * interrupted. */
  status?: "running" | "complete" | "incomplete" | "failed" | null;
  /** Cold-path pause latch (``usage.paused``). Write keeps ``status=running``;
   * when true, hydrate as paused (not streaming) — finishReason=paused. */
  paused?: boolean | null;
  /** 消息来源（如 execution_harvest）；写入 usage JSON，读路径投影到此字段. */
  origin?: string | null;
  /** 回合轮次 (Tier 2 重载持久化): ReAct rounds the turn ran, projected from the same column.
   * Replayed onto `message.rounds`; the bubble surfaces「N 轮」only when > 1. null for
   * user / pre-feature rows. */
  rounds?: number | null;
  /** 协作质量 (学·度量 §2.5): orchestration signals for 诊断模式; nested in usage column. */
  collab?: {
    boundary_yields: number;
    scope_signals: number;
    revises: number;
    escalations: number;
    audit_drops?: number;
  } | null;
  /** 回合 ¥ 成本 (P2 DERIVED)：messages.cost 列；重载 footer 直接用。 */
  cost?: import("@/services/usage").CostBreakdown | null;
  created_at: string;
}

/** A loaded slice of a conversation, plus the flags that drive infinite scroll. */
export interface MessageWindow {
  messages: Message[];
  total: number;
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  /** 记忆更新对话内可见 (§1.6): the conversation-tail「记忆已更新」cards. Backend returns
   * these ONLY for the latest window (the cards sit after the last message); empty on
   * scroll-up / around pages. */
  memoryUpdates: MemoryUpdate[];
}

/** Map a persisted `memory_updates` row (REST `MemoryUpdateView`) to the client's
 * domain {@link MemoryUpdate} for the conversation-tail card. */
export function toMemoryUpdate(m: Schemas["MemoryUpdateView"]): MemoryUpdate {
  const kind = m.kind === "episodic" ? "episodic" : "semantic";
  return {
    id: m.id,
    createdAt: m.created_at,
    kind,
    summary: m.summary ?? null,
    items: (m.items ?? []).map((it) => ({
      action: it.action,
      file: it.file,
      section: it.section,
      scope: it.scope,
      content: it.content,
      target: it.target,
      projectId: it.project_id ?? null,
    })),
  };
}

/** The execution (plan) id of a reloaded multi-agent turn — the first
 * `run_plan`'s id in the persisted journal. null for user / single-agent turns
 * (no journal, or a journal with no plan), which then render as plain bubbles. */
function executionIdOf(events: SSEEvent[]): string | null {
  const plan = events.find((e) => e.type === "run_plan");
  const id = (plan?.payload as { execution_id?: string } | undefined)
    ?.execution_id;
  return id ?? null;
}

/** Map a persisted message row to the client's domain {@link Message}, rebuilding
 * its team graph / checkpoint projections from the journal so a reloaded turn
 * renders exactly like its live one did. */
export function toMessage(m: BackendMessage): Message {
  const events = m.runs?.events ?? [];
  const executionId = executionIdOf(events);
  // Journal → InteractionStore (P2 unified store; reload path).
  // Cold/hot cards render from InteractionStore — no Message field dual-write.
  if (events.length > 0) {
    hydrateInteractionsFromJournal(m.conversation_id, m.id, events);
  }
  // Cold-path pause latch: InteractionStore alone does not paint ResumePrompt
  // (it reads pausedTurns). Mirror live message_end → surfaceResume when the
  // persisted row is still paused, so reopen / offline hydrate shows the card
  // even if /recovery raced empty.
  const paused = Boolean(m.paused);
  if (paused && m.role === "assistant" && events.length > 0) {
    const priorUser = [...getRuntime(m.conversation_id).messages]
      .reverse()
      .find((msg) => msg.role === "user");
    surfaceResumeFromAssistant(
      m.conversation_id,
      { id: m.id, serverMessageId: m.id },
      "server",
      { content: priorUser?.content, id: priorUser?.id },
    );
  }
  // steps — now for single-agent AND multi-agent turns (统一团队时间线). Single-agent
  // tool-less turns synthesize one reasoning step from reasoning_content.
  const baseProcess: ProcessStep[] | undefined =
    m.runs?.process ??
    (!executionId && m.reasoning_content
      ? [{ kind: "reasoning", text: m.reasoning_content }]
      : undefined);
  // 补标记（时间线一期）: backfill positional markers the journal implies (`team` /
  // `team_preview` / `checkpoint` / `ask` / `plan_review`) so the invariant「有交互卡
  // 必有时间线标记」holds on reload — the bottom-stack fallback is gone, an unmarked
  // card would silently vanish. Dedup no-ops when the persisted process already
  // carries them (the normal case).
  const process: ProcessStep[] | undefined =
    events.length > 0
      ? ensureTimelineMarkersFromJournal(baseProcess, events)
      : baseProcess;
  // On reload the row `id` IS the server message_id. Stamp `serverMessageId` so
  // resume guards (`isClientOnlyResumeKey`) match the live path (message_start stamp)
  // and do not treat a hydrated assistant as client-only.
  const role = m.role === "assistant" ? "assistant" : "user";
  // P4: running → stream-style partial; incomplete / interrupted finish → interrupted chip.
  // Cold-path pause latch: write keeps status=running + paused=true; hydrate as paused
  // (not streaming) so reopen does not setGenerating / spinner forever.
  const status = m.status ?? null;
  const finishReason = paused
    ? "paused"
    : (m.runs?.finish_reason ??
      (status === "incomplete" ? "interrupted" : undefined) ??
      undefined);
  const isStreaming = role === "assistant" && status === "running" && !paused;
  const mapped: Message = {
    id: m.id,
    ...(role === "assistant" ? { serverMessageId: m.id } : {}),
    role,
    content: m.content ?? "",
    reasoning: m.reasoning_content ?? undefined,
    // 关联气泡↔日志: replay the turn's trace_id so a reloaded bubble's「复制诊断信息」
    // includes it for log_timeline.py --trace.
    traceId: m.trace_id ?? undefined,
    process,
    createdAt: m.created_at,
    // Stamp the plan id so the bubble renders its inline team graph; the journal
    // below lets that graph replay the turn (both null for non-team turns).
    executionId,
    runs: executionId
      ? {
          events,
          finishReason: finishReason ?? "stop",
          runProcesses: m.runs?.run_processes ?? null,
        }
      : undefined,
    // 结束原因 chip (Tier 2 c): surface the persisted finish_reason turn-level so a
    // single-agent abnormal turn (max_rounds / degraded / unproductive) replays its
    // chip on reload too — the bubble reads `finishReason ?? runs?.finishReason`, and a
    // single-agent turn has no `runs`. A clean turn carries no journal → undefined → no
    // chip. (Multi-agent also keeps its `runs.finishReason` above; this is redundant but
    // harmless there.)
    finishReason,
    status,
    // 报错回合 error card (Tier 2 a): replay the inline error card from the persisted
    // outcome, mirroring the live `error` event handler's `{code, message}` attach.
    error: m.runs?.error ?? undefined,
    // 回合 token 用量 + 轮次 (Tier 2 重载): replay the bubble's meta row from the persisted
    // turn snapshot, mirroring the live `attachTurnMetaToLastMessage` stamp — usage is
    // already the ledger short-key shape (normalized server-side), rounds drives the
    // 「N 轮」caption. Both undefined for user / no-spend turns → no meta row (live parity).
    usage: m.usage ?? undefined,
    rounds: m.rounds ?? undefined,
    collab: m.collab ?? undefined,
    // 下一步推荐 chips (DERIVED 持久化): replay the last turn's persisted chips on reload,
    // mirroring the live `attachFollowups` stamp (twin of the title). Empty []
    // server-side → undefined; ChatView / CanvasCommandBar only surface them on the
    // latest finished turn.
    followups: m.followups?.length ? m.followups : undefined,
    // 回复反馈 (点赞/点踩): replay the persisted rating so a reloaded bubble shows the
    // user's thumbs; null server-side → null (未评价).
    feedback: m.feedback ?? null,
    // 回合 ¥ 成本 (P2 DERIVED)：messages.cost 列；重载 footer 直接用（hover 明细仍走 GET …/cost）。
    cost: m.cost ?? undefined,
    // 预检警告（P2）：runs 投影抬升的 turn_warning → 消息横幅。
    turnWarning: m.runs?.turn_warning ?? undefined,
    // 收到的上下文 · CEO 侧 (上下文传递可视化 通道①): turn-level, so it replays independently
    // of the team graph — present on pure-chat reloads (empty `events`) too.
    captainContext: m.runs?.captain_context?.length
      ? m.runs.captain_context
      : undefined,
    isStreaming,
    attachments: m.attachments?.length
      ? m.attachments.map((a) => ({
          id: crypto.randomUUID(),
          name: a.name,
          path: a.path,
          truncated: a.truncated,
          kind: a.kind ?? "file",
          workspacePath: a.workspace_path ?? undefined,
          conversationId: a.conversation_id ?? undefined,
        }))
      : undefined,
    citations: m.citations?.length
      ? m.citations.map((c) => ({
          url: c.url,
          title: c.title,
          snippet: c.snippet,
          site: c.site,
          id: c.id ?? undefined,
          date: c.date ?? undefined,
          tier: c.tier ?? undefined,
          query: c.query ?? undefined,
          deep_read: c.deep_read ?? undefined,
          registrant: c.registrant ?? undefined,
          citable: c.citable ?? undefined,
        }))
      : undefined,
    evidenceLedger: m.evidence_ledger?.length ? m.evidence_ledger : undefined,
    // REST origin（如 execution_harvest）；缺省时下方前缀兜底。
    origin: m.origin ?? undefined,
  };
  // 异步团队收口：优先 REST origin；正文前缀兜底旧数据。
  if (
    isExecutionHarvestMessage({
      role: mapped.role,
      content: mapped.content,
      origin: mapped.origin,
    })
  ) {
    mapped.origin = EXECUTION_HARVEST_ORIGIN;
  }
  return mapped;
}

/**
 * Whether a freshly loaded message window should paint live generating chrome.
 * Driven solely by {@link Message.isStreaming} (toMessage already maps cold-path
 * ``paused`` out of streaming). Ghost interrupted remains a separate recovery branch.
 */
export function shouldSetGeneratingOnHydrate(
  messages: { isStreaming?: boolean }[],
): boolean {
  return messages.at(-1)?.isStreaming === true;
}

/** How to window a conversation's messages — mutually exclusive (the backend
 * checks `around` → `before` → `after` → latest in that order). */
export interface MessageWindowQuery {
  /** Center the window on this message id (search-hit jump, load-around B). */
  around?: string;
  /** Load the page strictly older than this ISO cursor (scroll up). */
  before?: string;
  /** Load the page strictly newer than this ISO cursor (scroll down). */
  after?: string;
  /** Page size per direction (default = backend default of 100). */
  limit?: number;
}

/**
 * Fetch one window of a conversation's messages.
 *
 * No params → the latest window (conversation open). `around`/`before`/`after`
 * drive the search-hit jump and infinite scroll. The returned `hasMore*` flags
 * tell the caller whether more remain in each direction.
 */
export async function fetchMessageWindow(
  conversationId: string,
  query: MessageWindowQuery = {},
): Promise<MessageWindow> {
  const params = new URLSearchParams();
  if (query.around) params.set("around", query.around);
  if (query.before) params.set("before", query.before);
  if (query.after) params.set("after", query.after);
  if (query.limit != null) params.set("limit", String(query.limit));
  const qs = params.toString();
  const res = await api.get<BackendMessageListResponse>(
    `/v1/conversations/${conversationId}/messages${qs ? `?${qs}` : ""}`,
  );
  const rows = res.data as unknown as BackendMessage[];
  return {
    messages: rows.map((m) => toMessage(m)),
    total: res.total,
    hasMoreBefore: res.has_more_before,
    hasMoreAfter: res.has_more_after,
    memoryUpdates: (res.memory_updates ?? []).map(toMemoryUpdate),
  };
}

/** ISO `createdAt` of a conversation slice's oldest / newest loaded message, or
 * null when empty. The cursors infinite scroll pages from. */
function edgeCursors(conversationId: string): {
  oldest: string | null;
  newest: string | null;
} {
  const slice = useConversationStore.getState().byId[conversationId]?.messages;
  if (!slice || slice.length === 0) return { oldest: null, newest: null };
  return {
    oldest: slice[0].createdAt,
    newest: slice[slice.length - 1].createdAt,
  };
}

/**
 * Load the page just older than what's loaded and prepend it (scroll up).
 * No-op when nothing more remains or a load is already in flight, so a burst of
 * scroll events collapses into one request.
 */
export async function loadOlderMessages(conversationId: string): Promise<void> {
  const store = useConversationStore.getState();
  const rt = store.byId[conversationId];
  if (!rt || !rt.hasMoreBefore || rt.loadingOlder) return;
  const { oldest } = edgeCursors(conversationId);
  if (!oldest) return;
  store.setLoadingOlder(true, conversationId);
  try {
    const win = await fetchMessageWindow(conversationId, { before: oldest });
    useConversationStore
      .getState()
      .prependMessages(win.messages, win.hasMoreBefore, conversationId);
  } catch {
    /* best-effort: a failed page just leaves the older button to retry on scroll */
  } finally {
    useConversationStore.getState().setLoadingOlder(false, conversationId);
  }
}

/**
 * Load the page just newer than what's loaded and append it (scroll down).
 * Only meaningful after a load-around jump left newer history unloaded
 * (`hasMoreAfter`); a no-op at the live head.
 */
export async function loadNewerMessages(conversationId: string): Promise<void> {
  const store = useConversationStore.getState();
  const rt = store.byId[conversationId];
  if (!rt || !rt.hasMoreAfter || rt.loadingNewer) return;
  const { newest } = edgeCursors(conversationId);
  if (!newest) return;
  store.setLoadingNewer(true, conversationId);
  try {
    const win = await fetchMessageWindow(conversationId, { after: newest });
    useConversationStore
      .getState()
      .appendNewerMessages(win.messages, win.hasMoreAfter, conversationId);
  } catch {
    /* best-effort */
  } finally {
    useConversationStore.getState().setLoadingNewer(false, conversationId);
  }
}

/**
 * Reload the latest window, replacing whatever is on screen. Used to snap back
 * to the live head before a new turn when the user is reading a historical
 * window (a search-hit jump left `hasMoreAfter`), so the turn appends at the
 * true tail rather than into a mid-conversation gap.
 */
export async function loadLatestWindow(conversationId: string): Promise<void> {
  const win = await fetchMessageWindow(conversationId);
  const store = useConversationStore.getState();
  store.setMessageWindow(
    win.messages,
    { hasMoreBefore: win.hasMoreBefore, hasMoreAfter: win.hasMoreAfter },
    conversationId,
  );
  // Latest window owns the tail cards; replace them (older/around pages return none).
  store.setMemoryUpdates(win.memoryUpdates, conversationId);
}

/**
 * Jump the conversation to a specific message (search-hit "命中必达").
 *
 * If the message is already in the loaded window, just scroll to it. Otherwise
 * fetch a window centered on it (load-around B), swap it in, then focus — so a hit
 * outside the latest 100 still lands precisely. Assumes `conversationId` is (or is
 * becoming) the active conversation; the caller navigates there first.
 */
export async function jumpToMessage(
  conversationId: string,
  messageId: string,
): Promise<void> {
  const store = useConversationStore.getState();
  const rt = store.byId[conversationId];
  // Permalink / search may carry the server turn id while the live bubble still
  // keys on a client UUID — match either, then focus by the store bubble id.
  const present = rt?.messages.find(
    (m) => m.id === messageId || m.serverMessageId === messageId,
  );
  if (present) {
    store.focusMessage(present.id);
    return;
  }
  try {
    const win = await fetchMessageWindow(conversationId, { around: messageId });
    const after = useConversationStore.getState();
    // The user may have navigated away while the window loaded — only swap it in
    // if this conversation is still the one on screen.
    if ((after.currentConversationId ?? "") !== conversationId) return;
    after.setMessageWindow(
      win.messages,
      { hasMoreBefore: win.hasMoreBefore, hasMoreAfter: win.hasMoreAfter },
      conversationId,
    );
    // The tail cards belong only to the live tail; an around-window has none, so this
    // clears any cards left from the latest view (they'd otherwise float after the
    // historical window). They return on the next latest-window load.
    after.setMemoryUpdates(win.memoryUpdates, conversationId);
    // Focus on the next frame so the bubbles have rendered before we scroll.
    requestAnimationFrame(() => {
      const msgs =
        useConversationStore.getState().byId[conversationId]?.messages ?? [];
      const hit = msgs.find(
        (m) => m.id === messageId || m.serverMessageId === messageId,
      );
      if (hit) useConversationStore.getState().focusMessage(hit.id);
    });
  } catch {
    /* message gone / not owned — leave the conversation as-is */
  }
}

/**
 * Delete a single message (单条消息删除). Removes the row server-side, then drops
 * it from the conversation's live window. Server-first so a failed delete leaves
 * the message on screen; throws on failure so the caller can surface a toast.
 * Append-only cost ledger is untouched server-side (real spend is never rewritten).
 */
export async function deleteMessage(
  conversationId: string,
  messageId: string,
): Promise<void> {
  await api.delete(`/v1/conversations/${conversationId}/messages/${messageId}`);
  useConversationStore.getState().removeMessage(messageId, conversationId);
}

/**
 * Set / clear the user's 点赞/点踩 on an assistant reply (回复反馈). Optimistic: the
 * bubble flips immediately, then persists; a failed PATCH reverts to the prior rating
 * and rethrows so the caller can toast. `feedback` is "up" / "down" to rate, or null to
 * clear (clicking the active side again toggles it off).
 */
export async function setMessageFeedback(
  conversationId: string,
  messageId: string,
  feedback: "up" | "down" | null,
): Promise<void> {
  const store = useConversationStore.getState();
  const prev =
    store.byId[conversationId]?.messages.find((m) => m.id === messageId)
      ?.feedback ?? null;
  store.updateMessage(messageId, { feedback });
  try {
    await api.patch(
      `/v1/conversations/${conversationId}/messages/${messageId}/feedback`,
      { feedback },
    );
  } catch (err) {
    useConversationStore
      .getState()
      .updateMessage(messageId, { feedback: prev });
    throw err;
  }
}
