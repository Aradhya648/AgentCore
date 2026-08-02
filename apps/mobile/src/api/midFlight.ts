/**
 * Mid-flight send（生成中再发）：POST 恒 SSE。
 * 协调 + steer → `user_interjection` 短确认；经典 + steer → `turn_steer_accepted` toast；
 * queue（或 steer 降级）→ 先 `turn_queued`（立即主时间线用户气泡 + 排队轻态），
 * 缓冲后续帧直至主路空闲，再续流 turn2——对齐桌面 midFlight / 发送即有流。
 * ``delivery`` 必填（缺 → 422）。
 */
import { apiUrl, authHeader, refreshTokens } from "@/api/client";
import type { MessageAttachment } from "@/lib/attachments";
import { StreamHttpError } from "@/lib/errors";
import type { MessageDelivery } from "@/lib/messageDelivery";
import type {
  SSEEvent,
  TurnQueuedPayload,
  TurnSteerAcceptedPayload,
} from "@agentcore/contract-types";

export type MidFlightSendResult =
  | { kind: "received" }
  | {
      kind: "steered";
      steerId: string;
      pending: number;
    }
  | {
      kind: "queued";
      position: number;
      queueDepth: number;
      queueId: string;
      degradedFrom?: "steer";
    }
  | { kind: "blocked"; code?: string; message?: string }
  | { kind: "error"; message: string };

type DeliverMode = "open" | "buffering" | "live" | "aborted";

export type MidFlightHooks = {
  /** 立即 fold 到当前 live turn（user_interjection / turn_steer_accepted；turn_queued 亦可）。 */
  onLiveEvent: (event: SSEEvent) => void;
  /**
   * ``turn_queued``：立即主时间线用户气泡 + 排队轻态（drain 前可取消）。
   * 先于缓冲 / beginTurn2；多项各调一次（各 queue_id）。
   */
  onQueued: (info: {
    queueId: string;
    position: number;
    queueDepth: number;
    degradedFrom?: "steer";
  }) => void;
  /**
   * 主路空闲后开跑 turn2（只调一次）。
   * 用户气泡应已由 {@link onQueued} 插入——此处勿再插泡。
   */
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
  delivery: MessageDelivery = "steer",
): Promise<MidFlightSendResult> {
  const payload: Record<string, unknown> = { content, delivery };
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
        result = { kind: "received" };
        hooks.onLiveEvent(event);
        return;
      }

      if (event.type === "turn_steer_accepted") {
        const p = event.payload as TurnSteerAcceptedPayload;
        gate.mode = "live";
        result = {
          kind: "steered",
          steerId: p.steer_id,
          pending: p.pending,
        };
        hooks.onLiveEvent(event);
        return;
      }

      if (event.type === "turn_queued") {
        const p = event.payload as TurnQueuedPayload;
        const position = p.position ?? 1;
        const queueDepth = p.queue_depth ?? 1;
        const queueId = p.queue_id;
        result = {
          kind: "queued",
          position,
          queueDepth,
          queueId,
          degradedFrom: p.degraded_from,
        };
        // 立即主时间线用户气泡 + 排队轻态（产品：Queue 可见可取消）。
        hooks.onQueued({
          queueId,
          position,
          queueDepth,
          degradedFrom: p.degraded_from,
        });
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
