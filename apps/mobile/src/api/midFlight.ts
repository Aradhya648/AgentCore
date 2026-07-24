/**
 * Mid-flight send（生成中再发）：POST 恒 SSE。
 * 协调 → `user_interjection` 短确认；经典在飞 → 先 `turn_queued`（进 live turn 呈现排队条），
 * 缓冲后续帧直至主路空闲，再开 turn2 用户气泡并续流——对齐桌面 midFlight / 发送即有流。
 */
import { apiUrl, authHeader, refreshTokens } from "@/api/client";
import type { MessageAttachment } from "@/lib/attachments";
import { StreamHttpError } from "@/lib/errors";
import type { SSEEvent, TurnQueuedPayload } from "@agentcore/contract-types";

export type MidFlightSendResult =
  | { kind: "delivered" }
  | { kind: "queued"; position: number; queueDepth: number }
  | { kind: "blocked"; code?: string; message?: string }
  | { kind: "error"; message: string };

type DeliverMode = "open" | "buffering" | "live" | "aborted";

export type MidFlightHooks = {
  /** 立即 fold 到当前 live turn（turn_queued / user_interjection）。 */
  onLiveEvent: (event: SSEEvent) => void;
  /** 主路空闲后插入 turn2 用户气泡（只调一次）。 */
  beginTurn2: () => void;
  /** turn2 开跑后的事件（含缓冲回放）。 */
  onTurn2Event: (event: SSEEvent) => void;
  isPrimaryIdle: () => boolean;
  waitPrimaryIdle: () => Promise<void>;
};

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
    /* keep status-only */
  }
  return new StreamHttpError(response.status, code, serverMessage);
}

/** Minimal SSE pump（与 stream.ts 同形；仅 data: 帧）。 */
async function pumpSse(
  response: Response,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("无响应流");
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          onEvent(JSON.parse(line.slice(5).trim()) as SSEEvent);
        } catch {
          /* skip malformed */
        }
      }
    }
  }
}

export async function sendMidFlightMessage(
  conversationId: string,
  content: string,
  hooks: MidFlightHooks,
  attachments?: MessageAttachment[],
  signal?: AbortSignal,
): Promise<MidFlightSendResult> {
  const payload: Record<string, unknown> = { content };
  if (attachments && attachments.length > 0) payload.attachments = attachments;

  const gate = { mode: "open" as DeliverMode };
  const buffer: SSEEvent[] = [];
  let result: MidFlightSendResult = { kind: "error", message: "发送失败" };
  let turn2Started = false;

  const beginTurn2Once = (): void => {
    if (turn2Started) return;
    turn2Started = true;
    hooks.beginTurn2();
  };

  const dispatchTurn2 = (event: SSEEvent): void => {
    if (event.type === "message_start" && result.kind === "queued") {
      beginTurn2Once();
    }
    if (!turn2Started && result.kind === "queued") {
      beginTurn2Once();
    }
    hooks.onTurn2Event(event);
  };

  const flushBufferAndGoLive = (): void => {
    if (gate.mode === "aborted" || signal?.aborted) {
      gate.mode = "aborted";
      buffer.length = 0;
      return;
    }
    if (gate.mode !== "buffering") return;
    gate.mode = "live";
    const pending = buffer.splice(0);
    for (const ev of pending) dispatchTurn2(ev);
  };

  const doFetch = () =>
    fetch(apiUrl(`/v1/conversations/${conversationId}/messages`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeader(),
      },
      body: JSON.stringify(payload),
      signal,
    });

  try {
    let response = await doFetch();
    if (response.status === 401 && (await refreshTokens())) {
      response = await doFetch();
    }
    if (response.status === 409) {
      const err = await streamErrorFromResponse(response);
      return {
        kind: "blocked",
        code: err.code,
        message: err.serverMessage ?? "请先处理待确认事项",
      };
    }
    if (response.status === 202) {
      return {
        kind: "error",
        message: "服务端仍返回已退役的 202 排队受理",
      };
    }
    if (!response.ok) {
      const err = await streamErrorFromResponse(response);
      return {
        kind: "error",
        message: err.serverMessage ?? `HTTP ${response.status}`,
      };
    }

    await pumpSse(response, (event) => {
      if (gate.mode === "aborted" || signal?.aborted) return;

      if (event.type === "user_interjection") {
        gate.mode = "live";
        result = { kind: "delivered" };
        hooks.onLiveEvent(event);
        return;
      }

      if (event.type === "turn_queued") {
        const p = event.payload as TurnQueuedPayload;
        result = {
          kind: "queued",
          position: p.position ?? 1,
          queueDepth: p.queue_depth ?? 1,
        };
        hooks.onLiveEvent(event);
        gate.mode = "buffering";
        if (hooks.isPrimaryIdle()) flushBufferAndGoLive();
        else {
          void hooks.waitPrimaryIdle().then(() => {
            if (gate.mode === "buffering") flushBufferAndGoLive();
          });
        }
        return;
      }

      if (gate.mode === "buffering") {
        buffer.push(event);
        if (hooks.isPrimaryIdle()) flushBufferAndGoLive();
        return;
      }

      // 空闲竞态：主路已结束时 mid-flight 直接开 turn2。
      if (!turn2Started) beginTurn2Once();
      hooks.onTurn2Event(event);
    });

    if (signal?.aborted) {
      gate.mode = "aborted";
      buffer.length = 0;
      return result;
    }
    if (gate.mode === "buffering") {
      if (!hooks.isPrimaryIdle()) await hooks.waitPrimaryIdle();
      if (!signal?.aborted) flushBufferAndGoLive();
      else {
        gate.mode = "aborted";
        buffer.length = 0;
      }
    }
    return result;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      gate.mode = "aborted";
      buffer.length = 0;
      return result;
    }
    return {
      kind: "error",
      message: err instanceof Error ? err.message : "发送失败",
    };
  }
}
