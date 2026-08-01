import { apiFetch } from "@/api/client";
// Conversation REST for the mobile client (前端技术与架构 §七 · 会话管理).
//
// Bearer-authenticated reads/writes over the same cloud endpoints the desktop uses
// (api/routes/conversations.py). Pure data fetch — the chat transport (SSE) lives in
// stream.ts. REST DTOs track the backend OpenAPI spec via @agentcore/contract-rest-types;
// `runs.events` stays typed as SSEEvent[] (opaque JSON in OpenAPI — API 开发规范).
import type { components } from "@/types/api.generated";
import type {
  Citation,
  ContextBlockWire,
  ProcessStep,
  SSEEvent,
  TurnEvidenceLedgerEntry,
} from "@agentcore/contract-types";

type Schemas = components["schemas"];

/** A conversation row from the list/detail endpoints (server-shaped). */
export type ConversationSummary = Schemas["ConversationSummary"];

/** An assistant message's persisted replay payload (schemas.py RunsPayload).
 *  `events` is a MULTI-agent turn's ordered run/tool SSE journal (empty `[]` for a
 *  single-agent turn) — re-fold it through the SAME {@link fold} as the live stream to
 *  reproduce the team graph on reload. `process` is a SINGLE-agent turn's 思考+工具
 *  timeline (verbatim ProcessStep[]; null unless a tool ran). `null` whole payload for a
 *  plain text turn. */
export interface RunsPayload {
  events: SSEEvent[];
  finish_reason: string | null;
  process: ProcessStep[] | null;
  /** 收到的上下文 · CEO 侧 (上下文传递可视化 通道①): the captain's `run_context` blocks,
   *  persisted turn-level so a pure-chat turn (empty `events`) still replays the CEO's
   *  received context on reload. `null` unless the captain shipped context. */
  captain_context?: ContextBlockWire[] | null;
  /** 预检警告（P2 DURABLE）：lifted turn_warning for plain-chat reload. */
  turn_warning?: string | null;
}

/** A user message's attachment as persisted (composer 附件). The agent-chat send ships the
 *  file text inline; the server durably stores it, so a reloaded turn carries only display
 *  metadata (name + truncation), not the content — enough to show context chips. */
export type AttachmentMeta = Pick<
  Schemas["StoredAttachment"],
  "name" | "truncated"
>;

export interface MessageDetail {
  id: string;
  role: string;
  content: string | null;
  reasoning_content: string | null;
  citations: Citation[];
  /** 回合调研台账（引用即出处 P1, DERIVED）：messages.evidence_ledger；`#rN` 冷启动。 */
  evidenceLedger?: TurnEvidenceLedgerEntry[];
  runs: RunsPayload | null;
  attachments?: AttachmentMeta[];
  /** Progressive assistant-row lifecycle (``usage.status`` · P4 hydrate). */
  status?: "running" | "complete" | "incomplete" | "failed" | null;
  /** Cold-path pause latch (``usage.paused``): hydrate as paused, not streaming. */
  paused?: boolean | null;
  /** 回合 ¥ 成本 (P2 DERIVED)：messages.cost 列；重载 footer 直接用。 */
  cost?: Schemas["CostBreakdown"] | null;
  /** CEO→用户「下一步」chips (DERIVED · messages.followups)；重载重现. */
  followups?: string[];
  /** 消息来源（如 execution_harvest 系统收口）；正文前缀为旧数据兜底. */
  origin?: string | null;
  /** 回合日志关联 id（messages.trace_id）—「复制排查包」冷启动. */
  trace_id?: string | null;
  created_at: string;
}

/** The latest page of the user's conversations (newest-first). `archived` selects the
 *  「已归档」view; the default live list excludes archived rows (backend default). */
export async function listConversations(
  archived = false,
): Promise<ConversationSummary[]> {
  const res = await apiFetch(
    `/v1/conversations?page=1&page_size=50&archived=${archived}`,
  );
  if (!res.ok) throw new Error(`加载会话列表失败 (${res.status})`);
  const data = (await res.json()) as Schemas["ConversationListResponse"];
  return data.data;
}

/** Fetch one conversation (owner-scoped). Includes ``permission_axes``. */
export async function getConversation(
  id: string,
): Promise<ConversationSummary> {
  const res = await apiFetch(`/v1/conversations/${id}`);
  if (!res.ok) throw new Error(`加载会话失败 (${res.status})`);
  return (await res.json()) as ConversationSummary;
}

/** Rename a conversation (对话管理 · 重命名). Returns the updated summary. */
export async function renameConversation(
  id: string,
  title: string,
): Promise<ConversationSummary> {
  const res = await apiFetch(`/v1/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`重命名失败 (${res.status})`);
  return (await res.json()) as ConversationSummary;
}

/** Switch this conversation's model combination. Pass a profile id to override the account
 *  default, or null to follow the account default. Returns the updated summary
 *  (`model_profile_id` is authoritative). */
export async function setConversationModelProfile(
  id: string,
  profileId: string | null,
): Promise<ConversationSummary> {
  const res = await apiFetch(`/v1/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_profile_id: profileId }),
  });
  if (!res.ok) {
    let message = `切换模型组合失败 (${res.status})`;
    try {
      const body = (await res.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      /* non-JSON body — keep the status-only phrasing */
    }
    throw new Error(message);
  }
  return (await res.json()) as ConversationSummary;
}

/** Archive (hide from the live list) or restore a conversation — reversible, no data
 *  loss (对话管理 · 归档/恢复). */
export async function setConversationArchived(
  id: string,
  archived: boolean,
): Promise<void> {
  const res = await apiFetch(`/v1/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ archived }),
  });
  if (!res.ok) {
    throw new Error(`${archived ? "归档" : "恢复"}失败 (${res.status})`);
  }
}

/** Permanently delete a conversation and its messages (对话管理 · 删除). */
export async function deleteConversation(id: string): Promise<void> {
  const res = await apiFetch(`/v1/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`删除失败 (${res.status})`);
}

/** Create a fresh cloud conversation and return its id (skeleton: no folder/mode). */
export async function createConversation(title?: string): Promise<string> {
  const res = await apiFetch("/v1/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title ?? null }),
  });
  if (!res.ok) throw new Error(`创建会话失败 (${res.status})`);
  const data = (await res.json()) as { id: string };
  return data.id;
}

/** One applied memory change in a 记忆已更新 card (Agent记忆与知识系统 §1.6; maps the OpenAPI
 *  MemoryUpdateItemView). `action` ∈ add/update/remove; `content` is the bullet (add/update) or
 *  the matched text (remove); `file`·`section` name the leaf; `scope` ∈ global/project; `target`
 *  is the desktop memory-leaf path (unused by the mobile lite card — it just opens AI 记忆). */
export interface MemoryUpdateItem {
  action: string;
  file: string;
  section: string;
  scope: string;
  content: string;
  target: string;
}

/** One offline-consolidation pass — what the AI remembered FROM this conversation (写也可见,
 *  §1.6). Returned ONLY with the latest messages window (the card sits at the thread tail).
 *  Mobile has no per-user firehose; ChatPage polls the latest window after message_end so
 *  the card can surface without requiring a full reopen. */
export interface MemoryUpdate {
  id: string;
  createdAt: string;
  kind: "episodic" | "semantic";
  summary?: string | null;
  items: MemoryUpdateItem[];
}

/** A window of messages plus whether older ones exist (drives 加载更早). `memoryUpdates` is
 *  the conversation-tail 记忆已更新 cards — non-empty only on the latest window. */
export interface MessageWindow {
  messages: MessageDetail[];
  hasMoreBefore: boolean;
  memoryUpdates: MemoryUpdate[];
}

/** Map one OpenAPI MessageDetail row → mobile {@link MessageDetail} (incl. evidence_ledger). */
export function toMessageDetail(row: Schemas["MessageDetail"]): MessageDetail {
  const runs = row.runs;
  const status = row.status ?? null;
  // Cold-path pause latch: write keeps status=running + paused=true; hydrate as
  // paused (finish_reason=paused) so reopen does not paint forever-streaming chrome.
  const paused = Boolean(row.paused);
  const finish = paused
    ? "paused"
    : (runs?.finish_reason ?? (status === "incomplete" ? "interrupted" : null));
  return {
    id: row.id,
    role: row.role,
    content: row.content,
    reasoning_content: row.reasoning_content ?? null,
    citations: (row.citations ?? []) as Citation[],
    evidenceLedger: row.evidence_ledger?.length
      ? (row.evidence_ledger as TurnEvidenceLedgerEntry[])
      : undefined,
    runs: runs
      ? {
          events: (runs.events ?? []) as unknown as SSEEvent[],
          finish_reason: finish,
          process: (runs.process ?? null) as ProcessStep[] | null,
          captain_context: (runs.captain_context ?? null) as
            | ContextBlockWire[]
            | null,
          turn_warning: runs.turn_warning ?? null,
        }
      : paused
        ? {
            events: [],
            finish_reason: "paused",
            process: null,
          }
        : status === "incomplete"
          ? {
              events: [],
              finish_reason: "interrupted",
              process: null,
            }
          : null,
    status,
    paused: paused || null,
    attachments: row.attachments?.map((a) => ({
      name: a.name,
      truncated: a.truncated,
    })),
    cost: row.cost ?? null,
    followups: row.followups?.length ? row.followups : undefined,
    origin: row.origin ?? null,
    trace_id: row.trace_id ?? null,
    created_at: row.created_at,
  };
}

/** The latest window of a conversation's messages (chronological, oldest-first), or —
 *  with `before` (an ISO cursor) — the page strictly older than it (scroll-up). The
 *  endpoint windows at ≤200; we load 100 at a time and use `has_more_before` to know
 *  whether to keep paging back. */
export async function getMessages(
  conversationId: string,
  before?: string,
): Promise<MessageWindow> {
  const cursor = before ? `&before=${encodeURIComponent(before)}` : "";
  const res = await apiFetch(
    `/v1/conversations/${conversationId}/messages?limit=100${cursor}`,
  );
  if (!res.ok) throw new Error(`加载消息失败 (${res.status})`);
  const data = (await res.json()) as Schemas["MessageListResponse"];
  return {
    messages: data.data.map(toMessageDetail),
    hasMoreBefore: data.has_more_before,
    // Backend returns these only on the latest window; older/around pages send none.
    memoryUpdates: (data.memory_updates ?? []).map((u) => ({
      id: u.id,
      createdAt: u.created_at,
      kind: u.kind === "episodic" ? "episodic" : "semantic",
      summary: u.summary ?? null,
      items: (u.items ?? []).map((it) => ({
        action: it.action,
        file: it.file,
        section: it.section,
        scope: it.scope,
        content: it.content,
        target: it.target,
      })),
    })),
  };
}
