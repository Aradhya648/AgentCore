import type { MessageDelivery } from "@/lib/composerDelivery";
import { notifyError } from "@/lib/toast";
import {
  BASE_URL,
  getCsrfHeaders,
  notifyUnauthorized,
  tryRefresh,
} from "@/services/api";
import { dispatchSSEEvent } from "@/services/sse/dispatch";
import {
  type OutgoingAttachment,
  pumpSseBody,
} from "@/services/streamConversation";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { useQueuedTurnsStore } from "@/stores/queuedTurns";
import type {
  SSEEvent,
  TurnQueuedPayload,
  TurnSteerAcceptedPayload,
} from "@/types/events";
import {
  claimPrimaryStream,
  isPrimaryStreamIdle,
  onPrimaryStreamIdle,
  releasePrimaryStream,
  waitForPrimaryStreamIdle,
} from "./streamOwnership";

export type MidFlightSendResult =
  | { kind: "received"; interjectionId: string }
  /** 经典+steer 真软插入 ack（``turn_steer_accepted``）。 */
  | { kind: "steered"; steerId: string }
  | { kind: "queued"; position: number; queueDepth: number; queueId: string }
  | { kind: "blocked"; code?: string }
  | { kind: "error" };

type DeliverMode = "open" | "buffering" | "live" | "aborted";

/**
 * POST a user message while a turn is already streaming（发送即有流）.
 *
 * ``delivery=steer``：
 * - 协调 → ``user_interjection`` 短确认（主时间线由 InterjectionTimeline 投影）
 * - 经典 → ``turn_steer_accepted``（软插入 pending；下一工具步生效）
 * - 不可注入 → ``turn_queued`` + ``degraded_from=steer``
 * ``delivery=queue``（强制）→ ``turn_queued`` 后立即插用户气泡 + 排队轻态，
 * 后续帧缓冲至 turn1 主路释放再续流。
 *
 * POST 在调用时刻发出（D9 FIFO 位次已占）；缓冲只推迟客户端 fold。
 * Stop/abort **不** cancel 服务端队列（可见条仍可按项取消）。
 */
export async function sendMidFlightMessage(
  conversationId: string,
  content: string,
  attachments: OutgoingAttachment[] | undefined,
  delivery: MessageDelivery,
): Promise<MidFlightSendResult> {
  const body: Record<string, unknown> = { content, delivery };
  if (attachments && attachments.length > 0) body.attachments = attachments;

  const ac = new AbortController();
  let abortRegistered = false;
  let result: MidFlightSendResult = { kind: "error" };
  let userMessageId: string | null = null;
  let trackedQueueId: string | null = null;
  /** 闭包内可变；对象字段避免 TS 把字面量 mode 收窄成永 false。 */
  const gate = { mode: "open" as DeliverMode };
  const buffer: SSEEvent[] = [];
  let queuedPrimaryToken: string | null = null;
  let unsubIdle: () => void = () => {};

  // 与 turn1 AbortSignal 联动：断连丢缓冲，**不** cancel 服务端队列（D9）。
  // 注意：stopGeneration 诚实停止不 abort AbortSignal，排队连接可继续等 drain。
  const parentAbort = getRuntime(conversationId).abort;
  const onParentAbort = (): void => ac.abort();
  parentAbort?.signal.addEventListener("abort", onParentAbort);

  const insertQueuedUserBubble = (
    queueId: string,
    position: number,
    queueDepth: number,
    degradedFrom?: "steer",
  ): void => {
    if (userMessageId) return;
    const id = crypto.randomUUID();
    userMessageId = id;
    trackedQueueId = queueId;
    useConversationStore.getState().addMessage(
      {
        id,
        role: "user",
        content,
        createdAt: new Date().toISOString(),
        executionId: null,
        isStreaming: false,
        attachments:
          attachments && attachments.length > 0
            ? attachments.map((a, i) => ({
                id: `mf-att-${i}`,
                name: a.name,
                path: a.path,
                truncated: a.truncated,
                kind: a.kind,
                conversationId: a.conversation_id,
                workspacePath: a.workspace_path,
              }))
            : undefined,
      },
      conversationId,
    );
    useQueuedTurnsStore.getState().upsert({
      queueId,
      conversationId,
      messageId: id,
      content,
      position,
      queueDepth,
      degradedFrom,
    });
    if (!abortRegistered) {
      useConversationStore.getState().setAbort(ac, conversationId);
      abortRegistered = true;
    }
  };

  const clearQueueLightState = (): void => {
    if (!trackedQueueId) return;
    useQueuedTurnsStore.getState().remove(conversationId, trackedQueueId);
    trackedQueueId = null;
  };

  const dispatchOne = (event: SSEEvent): void => {
    if (event.type === "message_start" && result.kind === "queued") {
      // drain 开跑：清排队轻态，保留用户气泡。
      clearQueueLightState();
      if (!userMessageId) {
        // 防御：未在 turn_queued 插泡（不应发生）——补插再续。
        insertQueuedUserBubble(
          result.queueId,
          result.position,
          result.queueDepth,
        );
      }
    }
    dispatchSSEEvent(event, { conversationId, source: "server" });
  };

  const discardBufferIfAborted = (): boolean => {
    if (!ac.signal.aborted && gate.mode !== "aborted") return false;
    gate.mode = "aborted";
    buffer.length = 0;
    unsubIdle();
    unsubIdle = () => {};
    return true;
  };

  const flushBufferAndGoLive = (): void => {
    // release 与 abort 同刻：waiter 同步唤 flush 须先于 fold 挡下（泵 Abort 分支来不及）。
    if (discardBufferIfAborted()) return;
    if (gate.mode !== "buffering") return;
    gate.mode = "live";
    unsubIdle();
    unsubIdle = () => {};
    if (!queuedPrimaryToken) {
      queuedPrimaryToken = claimPrimaryStream(conversationId);
    }
    const pending = buffer.splice(0);
    for (const ev of pending) dispatchOne(ev);
  };

  const armIdleFlush = (): void => {
    unsubIdle();
    if (isPrimaryStreamIdle(conversationId)) {
      flushBufferAndGoLive();
      return;
    }
    unsubIdle = onPrimaryStreamIdle(conversationId, () => {
      if (discardBufferIfAborted()) return;
      if (gate.mode === "buffering") flushBufferAndGoLive();
    });
  };

  const doFetch = (signal: AbortSignal) =>
    fetch(`${BASE_URL}/v1/conversations/${conversationId}/messages`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...getCsrfHeaders("POST"),
      },
      body: JSON.stringify(body),
      signal,
    });

  try {
    let response = await doFetch(ac.signal);
    if (response.status === 401) {
      const outcome = await tryRefresh();
      if (outcome === "renewed") {
        response = await doFetch(ac.signal);
      } else if (outcome === "auth_dead") {
        notifyUnauthorized();
        return { kind: "error" };
      } else {
        notifyError(new Error("network"), "发送失败");
        return { kind: "error" };
      }
    }
    if (response.status === 409) {
      let code: string | undefined;
      try {
        const errBody = (await response.json()) as {
          error?: { code?: string; message?: string };
          detail?: { code?: string; message?: string } | string;
        };
        code =
          errBody.error?.code ??
          (typeof errBody.detail === "object"
            ? errBody.detail?.code
            : undefined);
        notifyError(
          new Error(errBody.error?.message ?? "请先处理待确认事项"),
          "请先处理待确认事项",
        );
      } catch {
        notifyError(new Error("请先处理待确认事项"), "请先处理待确认事项");
      }
      return { kind: "blocked", code };
    }
    if (response.status === 202) {
      notifyError(new Error("服务端仍返回已退役的 202 排队受理"), "发送失败");
      return { kind: "error" };
    }
    if (!response.ok) {
      notifyError(new Error(`HTTP ${response.status}`), "发送失败");
      return { kind: "error" };
    }

    await pumpSseBody(response, conversationId, (event: SSEEvent) => {
      if (gate.mode === "aborted" || ac.signal.aborted) return;

      if (event.type === "user_interjection") {
        // 协调插话：即时送达，不缓冲、不占主路门。
        gate.mode = "live";
        const p = event.payload as { interjection_id?: string };
        const iid = (p.interjection_id || "").trim();
        if (iid) result = { kind: "received", interjectionId: iid };
        dispatchSSEEvent(event, { conversationId, source: "server" });
        return;
      }

      if (event.type === "turn_steer_accepted") {
        // 经典 soft-insert ack：不插主时间线气泡；toast 由 messageStream 呈现。
        gate.mode = "live";
        const p = event.payload as TurnSteerAcceptedPayload;
        const sid = (p.steer_id || "").trim();
        if (sid) result = { kind: "steered", steerId: sid };
        dispatchSSEEvent(event, { conversationId, source: "server" });
        return;
      }

      if (event.type === "turn_queued") {
        const p = event.payload as TurnQueuedPayload;
        const position = p.position ?? 1;
        const queueDepth = p.queue_depth ?? 1;
        const queueId = p.queue_id;
        result = { kind: "queued", position, queueDepth, queueId };
        // 立即主时间线用户气泡 + 排队轻态（产品：Queue 可见可取消）。
        insertQueuedUserBubble(
          queueId,
          position,
          queueDepth,
          p.degraded_from === "steer" ? "steer" : undefined,
        );
        // toast / degraded 由 dispatch → messageStream 呈现。
        dispatchSSEEvent(event, { conversationId, source: "server" });
        gate.mode = "buffering";
        armIdleFlush();
        return;
      }

      if (gate.mode === "buffering") {
        buffer.push(event);
        if (isPrimaryStreamIdle(conversationId)) flushBufferAndGoLive();
        return;
      }

      dispatchOne(event);
    });

    // 泵正常结束但仍 buffering：主路空则放行；若已 abort（mock 流 close 未抛）则丢缓冲。
    if (ac.signal.aborted) {
      gate.mode = "aborted";
      buffer.length = 0;
      return result;
    }
    if (gate.mode === "buffering") {
      if (!isPrimaryStreamIdle(conversationId)) {
        await waitForPrimaryStreamIdle(conversationId);
      }
      if (!ac.signal.aborted) flushBufferAndGoLive();
      else {
        gate.mode = "aborted";
        buffer.length = 0;
      }
    }

    return result;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // 排队等待中断连：丢未放行缓冲；**保留**排队气泡/条（Stop ≠ 取消排队）。
      gate.mode = "aborted";
      buffer.length = 0;
      return result;
    }
    notifyError(err, "发送失败");
    return { kind: "error" };
  } finally {
    parentAbort?.signal.removeEventListener("abort", onParentAbort);
    unsubIdle();
    if (queuedPrimaryToken) {
      releasePrimaryStream(conversationId, queuedPrimaryToken);
      queuedPrimaryToken = null;
    }
    if (abortRegistered && getRuntime(conversationId).abort === ac) {
      useConversationStore.getState().setAbort(null, conversationId);
    }
  }
}
