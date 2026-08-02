import { StreamError } from "@/lib/errors";
import {
  BASE_URL,
  getCsrfHeaders,
  notifyUnauthorized,
  tryRefresh,
} from "@/services/api";
import type { PlanReviewUserDecision } from "@/services/planReview";
import {
  dispatchSSEEvent,
  flushPendingContent,
  flushPendingFrames,
} from "@/services/sse/dispatch";
import { traceTurnMilestone } from "@/services/turnTrace";
import {
  claimPrimaryStream,
  releasePrimaryStream,
} from "@/services/turns/streamOwnership";
import { getRuntime } from "@/stores/conversation";
import {
  enterTurnStreaming,
  throwIfCannotOpenStream,
} from "@/stores/conversation/turnPhaseActions";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import type { SSEEvent } from "@/types/events";

/** Max wait for response headers (connect + server accept). Distinct from {@link pumpSSE}'s
 *  idle timeout, which only applies once the body is streaming. */
const CONNECT_TIMEOUT_MS = 30_000;

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** `fetch` with a connect-phase ceiling; user `signal` abort still propagates as AbortError.
 * 同步拒绝已 abort 的 signal，避免连接超时窗口内仍发出请求。 */
async function fetchWithConnectTimeout(
  init: (signal: AbortSignal) => Promise<Response>,
  userSignal?: AbortSignal,
): Promise<Response> {
  if (userSignal?.aborted) {
    throw new DOMException("Aborted", "AbortError");
  }
  const fetchAc = new AbortController();
  const timer = setTimeout(() => fetchAc.abort(), CONNECT_TIMEOUT_MS);
  const onUserAbort = () => fetchAc.abort();
  userSignal?.addEventListener("abort", onUserAbort);
  try {
    return await init(fetchAc.signal);
  } catch (err) {
    if (isAbortError(err)) {
      if (userSignal?.aborted) throw err;
      throw new StreamError("network");
    }
    throw err;
  } finally {
    clearTimeout(timer);
    userSignal?.removeEventListener("abort", onUserAbort);
  }
}

/** Build a {@link StreamError} from a non-OK response. A refused turn (e.g. 429
 * for quota / rate limit) arrives as a plain JSON `{error:{code,message}}` body
 * with a `Retry-After` header — not an SSE stream — so pull those out for precise
 * UI phrasing. Falls back to status-only when the body isn't the expected shape. */
async function streamErrorFromResponse(
  response: Response,
): Promise<StreamError> {
  let code: string | undefined;
  let serverMessage: string | undefined;
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string };
      detail?: { code?: string; message?: string } | string;
    };
    code = body.error?.code;
    serverMessage = body.error?.message;
    if (!code && typeof body.detail === "object" && body.detail) {
      code = body.detail.code;
      serverMessage = body.detail.message ?? serverMessage;
    }
  } catch {
    /* non-JSON body — keep status-only phrasing */
  }
  const header = Number(response.headers.get("Retry-After"));
  return new StreamError("http", response.status, {
    code,
    serverMessage,
    retryAfter: Number.isFinite(header) && header > 0 ? header : undefined,
  });
}

/** Latest journal seq seen on this conversation's SSE (for Last-Event-ID). */
const lastEventIds = new Map<string, string>();

/** Read the cursor used for precise stream resume. */
export function peekLastEventId(conversationId: string): string | undefined {
  return lastEventIds.get(conversationId);
}

export function clearLastEventId(conversationId: string): void {
  lastEventIds.delete(conversationId);
}

/**
 * Drain an SSE response body, routing every `data:` event through
 * `dispatchSSEEvent` (or a custom ``onEvent``). Shared by the POST turn channel
 * (send / regenerate / resume / midFlight) and the GET re-attach channel
 * (实时重连续看 C1 · slice 1b) — every SSE consumer folds events through the one
 * dispatch, so a live stream, a reload, and a reconnect all rebuild identical state.
 *
 * Applies the idle stall watchdog: the backend heart-beats every ~15s while a
 * turn thinks, so a live connection always delivers bytes; total silence for the
 * timeout means the socket is dead (server / proxy dropped it), so we cancel and
 * raise a retriable network error rather than hang. This is an *idle* timeout,
 * never a total-duration cap — a long turn that keeps streaming (or just
 * heart-beating) is never cut off.
 *
 * Tracks the latest SSE ``id:`` (journal seq) per conversation for ``Last-Event-ID``
 * resume (流式回复持久化 P3).
 */
export async function pumpSseBody(
  response: Response,
  conversationId: string,
  onEvent?: (event: SSEEvent) => void,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) return;

  // 缺省 = 唯一 dispatch 通道（live / reload / reconnect）；调用方可注入 onEvent
  //（如 midFlight 在 message_start 前插入乐观用户气泡）。
  const deliver =
    onEvent ??
    ((event: SSEEvent) =>
      dispatchSSEEvent(event, { conversationId, source: "server" }));

  const decoder = new TextDecoder();
  let buffer = "";
  /** Most recent SSE ``id:`` in the current frame (reset each blank-line frame). */
  let frameId: string | null = null;

  const IDLE_TIMEOUT_MS = 60_000;
  const readChunk = (): ReturnType<typeof reader.read> =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        void reader.cancel().catch(() => {});
        reject(new StreamError("network"));
      }, IDLE_TIMEOUT_MS);
      reader.read().then(
        (r) => {
          clearTimeout(timer);
          resolve(r);
        },
        (e) => {
          clearTimeout(timer);
          reject(e);
        },
      );
    });

  while (true) {
    const { done, value } = await readChunk();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line === "") {
        frameId = null;
        continue;
      }
      if (line.startsWith("id:")) {
        const id = line.slice(3).trim();
        if (id) {
          frameId = id;
          lastEventIds.set(conversationId, id);
        }
        continue;
      }
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6)) as SSEEvent;
        if (frameId) lastEventIds.set(conversationId, frameId);
        deliver(event);
      } catch {
        /* malformed event — skip */
      }
    }
  }
}

/** Outcome of a re-attach attempt (执行与请求解耦 C1 · slice 1b). */
export type AttachOutcome = "attached" | "none";

/**
 * Re-attach to a conversation's in-flight turn and 续看 it live (C1 · slice 1b).
 *
 * Always sends ``Last-Event-ID`` (last journal seq, or ``0`` when none) so the
 * backend takes the journal-backed full-turn replay path (流式回复持久化 §3.6 ·
 * P3). Callers that clear-then-fold (``rejoinLiveTurn``) truncate the bubble /
 * process / execution before attach — the replay segment folds into the empty
 * placeholder.
 */
export async function attachConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<AttachOutcome> {
  throwIfCannotOpenStream(conversationId, signal);
  enterTurnStreaming(conversationId);
  const primaryToken = claimPrimaryStream(conversationId);

  const doFetch = (signal: AbortSignal) => {
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    // Always present → journal-backed full replay (header value observational).
    headers["Last-Event-ID"] = lastEventIds.get(conversationId) ?? "0";
    return fetch(`${BASE_URL}/v1/conversations/${conversationId}/stream`, {
      method: "GET",
      credentials: "include",
      headers,
      signal,
    });
  };

  try {
    let response = await fetchWithConnectTimeout(doFetch, signal);
    if (response.status === 401) {
      const outcome = await tryRefresh();
      if (outcome === "renewed") {
        response = await fetchWithConnectTimeout(doFetch, signal);
      } else if (outcome === "auth_dead") {
        notifyUnauthorized();
        throw new StreamError("auth");
      } else {
        throw new StreamError("network");
      }
      if (response.status === 401) {
        notifyUnauthorized();
        throw new StreamError("auth");
      }
    }
    if (response.status === 204) return "none";
    if (!response.ok) {
      throw await streamErrorFromResponse(response);
    }

    await pumpSseBody(response, conversationId);

    if (getRuntime(conversationId).isGenerating) {
      throw new StreamError("network");
    }
    return "attached";
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (err instanceof StreamError) throw err;
    throw new StreamError("network");
  } finally {
    flushPendingContent(conversationId);
    flushPendingFrames(conversationId);
    releasePrimaryStream(conversationId, primaryToken);
  }
}

/**
 * POST to an SSE endpoint and route every event through `dispatchSSEEvent`.
 *
 * 发送即有流：本端点恒返回 SSE（含 in-flight 时先发 ``turn_queued`` 再同连接
 * 续流；协调插话为 ``user_interjection`` 短确认流）。不再有 HTTP 202 JSON。
 */
async function runMessageStream(
  path: string,
  body: string,
  conversationId: string,
  signal?: AbortSignal,
): Promise<void> {
  clearInteractionPrompts(conversationId);
  throwIfCannotOpenStream(conversationId, signal);
  enterTurnStreaming(conversationId);
  const primaryToken = claimPrimaryStream(conversationId);

  const doFetch = (signal: AbortSignal) =>
    fetch(`${BASE_URL}${path}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...getCsrfHeaders("POST"),
      },
      body,
      signal,
    });

  try {
    traceTurnMilestone(conversationId, "fetch_start", { path });
    let response = await fetchWithConnectTimeout(doFetch, signal);
    traceTurnMilestone(conversationId, "fetch_response", {
      status: response.status,
      ok: response.ok,
    });
    if (response.status === 401) {
      const outcome = await tryRefresh();
      if (outcome === "renewed") {
        response = await fetchWithConnectTimeout(doFetch, signal);
      } else if (outcome === "auth_dead") {
        notifyUnauthorized();
        throw new StreamError("auth");
      } else {
        throw new StreamError("network");
      }
      if (response.status === 401) {
        notifyUnauthorized();
        throw new StreamError("auth");
      }
    }

    if (!response.ok) {
      throw await streamErrorFromResponse(response);
    }
    // 发送即有流：成功体必须是 SSE。202 在 fetch 里仍算 ok，但契约已退役——
    // 显式失败，避免把 JSON 体当 SSE 静默读完再误判断流。
    if (response.status === 202) {
      throw new StreamError("http", 202, {
        serverMessage: "服务端仍返回已退役的 202 排队受理，请升级后端后再试",
      });
    }

    await pumpSseBody(response, conversationId);

    if (getRuntime(conversationId).isGenerating) {
      throw new StreamError("network");
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (err instanceof StreamError) throw err;
    throw new StreamError("network");
  } finally {
    flushPendingContent(conversationId);
    flushPendingFrames(conversationId);
    releasePrimaryStream(conversationId, primaryToken);
  }
}

/** 发送给后端的附件载荷（含提取出的正文 / 引用即驻留元数据）。 */
export interface OutgoingAttachment {
  name: string;
  path: string;
  text: string;
  truncated: boolean;
  kind?: "file" | "dir" | "conversation";
  conversation_id?: string;
  /** 二进制驻留：无 UTF-8 正文。 */
  binary?: boolean;
  /** 客户端已写入工作区时的相对路径（``attachments/…``）。 */
  workspace_path?: string;
}

export interface StreamConversationOptions {
  conversationId: string;
  content: string;
  attachments?: OutgoingAttachment[];
  /** 必填分流（缺 → 服务端 422）。空闲开跑客户端仍带 ``steer``。 */
  delivery: "steer" | "queue";
  signal?: AbortSignal;
}

/** Send a user message and consume the SSE response stream (发送即有流).
 *
 * In-flight 时流上先到 ``turn_queued``（EPHEMERAL，dispatch 侧呈现「已排队」），
 * drain 后同连接续流整回合；协调插话为短确认流。 */
export async function streamConversation({
  conversationId,
  content,
  attachments,
  delivery,
  signal,
}: StreamConversationOptions): Promise<void> {
  const payload: Record<string, unknown> = { content, delivery };
  if (attachments && attachments.length > 0) payload.attachments = attachments;
  await runMessageStream(
    `/v1/conversations/${conversationId}/messages`,
    JSON.stringify(payload),
    conversationId,
    signal,
  );
}

export interface RegenerateConversationOptions {
  conversationId: string;
  messageId: string;
  content?: string;
  signal?: AbortSignal;
}

export async function regenerateConversation({
  conversationId,
  messageId,
  content,
  signal,
}: RegenerateConversationOptions): Promise<void> {
  const body = JSON.stringify(content !== undefined ? { content } : {});
  await runMessageStream(
    `/v1/conversations/${conversationId}/messages/${messageId}/regenerate`,
    body,
    conversationId,
    signal,
  );
}

export interface ResumeConversationOptions {
  conversationId: string;
  messageId: string;
  decision: PlanReviewUserDecision;
  note: string;
  selected?: string[];
  /** Structured website style pick (s0/s1/…). */
  signal?: AbortSignal;
}

export async function resumeConversation({
  conversationId,
  messageId,
  decision,
  note,
  selected = [],
  signal,
}: ResumeConversationOptions): Promise<void> {
  const body = JSON.stringify({
    decision,
    note,
    selected,
  });
  await runMessageStream(
    `/v1/conversations/${conversationId}/messages/${messageId}/resume`,
    body,
    conversationId,
    signal,
  );
}

export interface ResolveStageCardOptions {
  conversationId: string;
  stageCardId: string;
  decision: "start_debate" | "research_first";
  note?: string;
  motionOverride?: string | null;
  signal?: AbortSignal;
}

/** 批 B：推进卡 resolve → SSE 新回合（机制直起辩论或回灌调研）。 */
export async function resolveStageCardConversation({
  conversationId,
  stageCardId,
  decision,
  note = "",
  motionOverride = null,
  signal,
}: ResolveStageCardOptions): Promise<void> {
  const body = JSON.stringify({
    kind: "stage_card",
    decision,
    note,
    motion_override: motionOverride,
  });
  await runMessageStream(
    `/v1/conversations/${conversationId}/interactions/${stageCardId}`,
    body,
    conversationId,
    signal,
  );
}

// Re-export SSE dispatch surface (shared by cloud + sidecar paths).
export {
  dispatchSSEEvent,
  flushPendingContent,
  flushPendingFrames,
} from "./sse/dispatch";
