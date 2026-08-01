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
import type { SSEEvent, TurnQueuedPayload } from "@/types/events";
import {
  claimPrimaryStream,
  isPrimaryStreamIdle,
  onPrimaryStreamIdle,
  releasePrimaryStream,
  waitForPrimaryStreamIdle,
} from "./streamOwnership";

export type MidFlightSendResult =
  | { kind: "received"; interjectionId: string }
  /** @deprecated alias of received — keep until callers migrate */
  | { kind: "delivered"; interjectionId: string }
  | { kind: "queued"; position: number; queueDepth: number }
  | { kind: "blocked"; code?: string }
  | { kind: "error" };

type DeliverMode = "open" | "buffering" | "live" | "aborted";

/**
 * POST a user message while a turn is already streaming（发送即有流）.
 *
 * Coordination → short SSE confirm with ``user_interjection``（即时 dispatch，不经
 * 主路门；主时间线由 InterjectionTimeline 投影 execution.userInterjections）；
 * classic in-flight → ``turn_queued`` 后缓冲后续帧，直至 turn1 主路泵
 * 释放（含 message_end / followups / turn_saved），再插用户气泡并续流——守住
 * drain 边界双连接不交叉污染末条气泡。
 *
 * POST 在调用时刻发出（D9 FIFO 位次已占）；缓冲只推迟客户端 fold。
 */
export async function sendMidFlightMessage(
  conversationId: string,
  content: string,
  attachments?: OutgoingAttachment[],
): Promise<MidFlightSendResult> {
  const body: Record<string, unknown> = { content };
  if (attachments && attachments.length > 0) body.attachments = attachments;

  const ac = new AbortController();
  let abortRegistered = false;
  let result: MidFlightSendResult = { kind: "error" };
  let userInserted = false;
  /** 闭包内可变；对象字段避免 TS 把字面量 mode 收窄成永 false。 */
  const gate = { mode: "open" as DeliverMode };
  const buffer: SSEEvent[] = [];
  let queuedPrimaryToken: string | null = null;
  let unsubIdle: () => void = () => {};

  // 与 turn1 停止键联动：排队等待中断连 → 丢缓冲、不 cancel 服务端队列（D9 detached）。
  const parentAbort = getRuntime(conversationId).abort;
  const onParentAbort = (): void => ac.abort();
  parentAbort?.signal.addEventListener("abort", onParentAbort);
  const insertUserBeforeTurn2 = (): void => {
    if (userInserted) return;
    useConversationStore.getState().addMessage(
      {
        id: crypto.randomUUID(),
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
    userInserted = true;
    if (!abortRegistered) {
      useConversationStore.getState().setAbort(ac, conversationId);
      abortRegistered = true;
    }
  };

  const dispatchOne = (event: SSEEvent): void => {
    if (
      event.type === "message_start" &&
      result.kind === "queued" &&
      !userInserted
    ) {
      insertUserBeforeTurn2();
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

      if (event.type === "turn_queued") {
        const p = event.payload as TurnQueuedPayload;
        result = {
          kind: "queued",
          position: p.position ?? 1,
          queueDepth: p.queue_depth ?? 1,
        };
        // toast 立即呈现；后续帧等 turn1 主路释放。
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
      // 排队等待中停止：丢弃未放行缓冲（不 cancel 服务端回合 · D9 detached）。
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
