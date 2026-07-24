import { apiUrl, authHeader, refreshTokens } from "@/api/client";
import type { MessageAttachment } from "@/lib/attachments";
import { StreamHttpError } from "@/lib/errors";
// SSE transport for the mobile client (前端技术与架构 §七).
//
// The backend streams a turn as a POST returning text/event-stream (api/sse.py):
// frames are `event: <type>\ndata: {type,timestamp,payload}\n\n`, with `: ping`
// heartbeat comments. Because it's a fetch-streamed POST (not EventSource), the bearer
// header rides the request directly — the key reason bearer + SSE works on mobile.
//
// This layer is PURE TRANSPORT: it parses each `data:` frame into a typed SSEEvent and
// hands it to `onEvent`. All interpretation lives in the conformance-checked fold
// (src/protocol/fold.ts) — never re-fold here (cross-platform-frontend.mdc §四).
//
// 执行与请求解耦 (C1 · slice 1a/1b): a client disconnect no longer cancels a server
// turn — it runs detached and persists. So there are three SSE entry points that all
// fold through the SAME shape: `streamMessage` (fresh send), `attachStream` (rejoin a
// still-live run after a drop / on reopen), and `resumeStream` (continue a durably
// paused turn). An explicit 停止 is a separate JSON call (api/turn.ts).
import type { CheckpointDecision, SSEEvent } from "@agentcore/contract-types";

/** Build a {@link StreamHttpError} from a non-OK response. A refused turn (e.g.
 *  402 LLM_KEY_REQUIRED / 429 quota) arrives as plain JSON `{error:{code,message}}`,
 *  not an SSE stream — pull those out so ChatPage can offer「去配置」. */
async function streamErrorFromResponse(
  response: Response,
): Promise<StreamHttpError> {
  let code: string | undefined;
  let serverMessage: string | undefined;
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string };
    };
    code = body.error?.code;
    serverMessage = body.error?.message;
  } catch {
    /* non-JSON body — keep status-only phrasing */
  }
  return new StreamHttpError(response.status, code, serverMessage);
}

/** Raised when the SSE body goes silent too long (dead socket / proxy drop). */
export class StreamNetworkError extends Error {
  constructor() {
    super("network");
    this.name = "StreamNetworkError";
  }
}

/** Max silence while the body is open. The backend heart-beats every ~15s during a
 *  thinking turn, so a live connection always delivers bytes; total silence means the
 *  socket is dead — cancel and surface a retriable error (mirrors desktop streamConversation). */
const IDLE_TIMEOUT_MS = 60_000;

/** Latest journal seq per conversation (SSE ``id:`` → ``Last-Event-ID`` resume). */
const lastEventIds = new Map<string, string>();

/** Read an SSE response body to completion, delivering each parsed `data:` frame to
 *  `onEvent`. `event:` lines and `:` heartbeats are ignored (the data JSON already
 *  carries the type). Throws if the response has no readable body.
 *
 *  Applies the idle stall watchdog: an *idle* timeout, never a total-duration cap — a
 *  long turn that keeps streaming (or just heart-beating) is never cut off. */
async function pumpSSE(
  response: Response,
  onEvent: (event: SSEEvent) => void,
  conversationId?: string,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("无响应流");

  const decoder = new TextDecoder();
  let buffer = "";
  let frameId: string | null = null;

  const readChunk = (): ReturnType<typeof reader.read> =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        void reader.cancel().catch(() => {});
        reject(new StreamNetworkError());
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
    // SSE frames are separated by a blank line; keep the trailing partial in buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      frameId = null;
      for (const line of frame.split("\n")) {
        if (line.startsWith("id:")) {
          const id = line.slice(3).trim();
          if (id && conversationId) {
            frameId = id;
            lastEventIds.set(conversationId, id);
          }
          continue;
        }
        if (!line.startsWith("data:")) continue;
        try {
          if (frameId && conversationId)
            lastEventIds.set(conversationId, frameId);
          onEvent(JSON.parse(line.slice(5).trim()) as SSEEvent);
        } catch {
          // Skip a malformed/partial frame; the next read completes it.
        }
      }
    }
  }
}

/** Run a fetch with the shared 401 policy (refresh once, replay). The SSE channels read
 *  the body themselves, so they can't ride apiFetch — they mirror its policy here. */
async function sseFetch(doFetch: () => Promise<Response>): Promise<Response> {
  let response = await doFetch();
  if (response.status === 401 && (await refreshTokens())) {
    response = await doFetch();
  }
  return response;
}

/**
 * Stream a freshly-sent user message, delivering each parsed SSE event to `onEvent`.
 * Throws on a transport failure (non-2xx / no body) or when the passed `signal` aborts
 * (the user's 停止); backend `error` events arrive as normal events for the fold.
 *
 * Since 执行与请求解耦 (slice 1a) a dropped connection no longer kills the turn — it runs
 * detached — so a mid-stream throw means "rejoin it" (attachStream), not "resend".
 *
 * `attachments` carry extracted file text alongside the prompt (composer 附件); omitted from
 * the body when empty so a plain turn keeps the exact prior shape.
 */
export async function streamMessage(
  conversationId: string,
  content: string,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
  attachments?: MessageAttachment[],
): Promise<void> {
  const path = `/v1/conversations/${conversationId}/messages`;
  const payload: Record<string, unknown> = { content };
  if (attachments && attachments.length > 0) payload.attachments = attachments;
  const response = await sseFetch(() =>
    fetch(apiUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeader(),
      },
      body: JSON.stringify(payload),
      signal,
    }),
  );
  if (!response.ok) throw await streamErrorFromResponse(response);
  await pumpSSE(response, onEvent, conversationId);
}

/** Outcome of a re-attach attempt (执行与请求解耦 C1 · slice 1b). */
export type AttachOutcome =
  /** A live run was found; its transcript-so-far was replayed and the stream tailed
   *  to completion (or until the connection dropped — the caller distinguishes via the
   *  thrown error). */
  | "attached"
  /** No run is live for the conversation (204) — already finished / never started /
   *  suspended at a checkpoint. The caller falls back to the persisted transcript
   *  (reload) or durable resume. */
  | "none";

/**
 * Re-attach to a conversation's in-flight turn and 续看 it live (C1 · slice 1b).
 *
 * Always sends ``Last-Event-ID`` (last journal seq, or ``0`` when none) so the
 * backend takes the journal-backed full-turn replay path (流式回复持久化 §3.6).
 * Returns "none" on a 204 (nothing live to rejoin); throws on a transport drop
 * while attached (retriable) or on auth.
 */
export async function attachStream(
  conversationId: string,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<AttachOutcome> {
  const path = `/v1/conversations/${conversationId}/stream`;
  const response = await sseFetch(() => {
    const headers: Record<string, string> = {
      Accept: "text/event-stream",
      // Always present → journal-backed full replay (header value observational).
      "Last-Event-ID": lastEventIds.get(conversationId) ?? "0",
      ...authHeader(),
    };
    return fetch(apiUrl(path), {
      method: "GET",
      headers,
      signal,
    });
  });
  if (response.status === 204) return "none";
  if (!response.ok) throw await streamErrorFromResponse(response);
  await pumpSSE(response, onEvent, conversationId);
  return "attached";
}

/** The user's settlement of a durably-paused turn (mirrors backend ResumeTurnRequest).
 *  `note` steers an `adjust`; `selected` carries ask_user picks (ignored for plan_review).
 *  `style_id` is the structured website style pick when present. */
export interface ResumeTurnBody {
  decision: CheckpointDecision;
  note: string;
  selected: string[];
  style_id?: string;
}

/**
 * Continue a durably-paused turn via SSE (结构化挂起 2b `POST .../resume`).
 *
 * The turn paused at a plan_review / ask_user checkpoint and lost its live stream
 * (disconnect / restart); only its persisted frame survived. The backend claims the
 * frame (atomic — a second/stale call 404s) and drives the rest of the turn on a fresh
 * SSE, folded through the same path as a send. Throws on transport / claim failure.
 */
export async function resumeStream(
  conversationId: string,
  messageId: string,
  body: ResumeTurnBody,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const path = `/v1/conversations/${conversationId}/messages/${messageId}/resume`;
  const response = await sseFetch(() =>
    fetch(apiUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeader(),
      },
      body: JSON.stringify(body),
      signal,
    }),
  );
  if (!response.ok) throw await streamErrorFromResponse(response);
  await pumpSSE(response, onEvent, conversationId);
}

/**
 * Re-run from a persisted user message (regenerate endpoint · P4 interrupted retry).
 * Same SSE shape as ``streamMessage`` — fold through the caller's ``onEvent``.
 */
export async function regenerateStream(
  conversationId: string,
  userMessageId: string,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const path = `/v1/conversations/${conversationId}/messages/${userMessageId}/regenerate`;
  const response = await sseFetch(() =>
    fetch(apiUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeader(),
      },
      body: "{}",
      signal,
    }),
  );
  if (!response.ok) throw await streamErrorFromResponse(response);
  await pumpSSE(response, onEvent, conversationId);
}

/** @internal Test hook — production `pumpSSE` with the idle stall watchdog. */
export const pumpSSEForTests = pumpSSE;
