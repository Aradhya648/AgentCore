import { ApiError, api } from "@/services/api";
import { useConversationStore } from "@/stores/conversation";
import {
  type QueuedTurnEntry,
  useQueuedTurnsStore,
} from "@/stores/queuedTurns";

/**
 * 本地清排队项 + 对应乐观用户气泡（幂等）。
 * HTTP 取消成功 / 404、以及 SSE ``turn_queue_cancelled`` 共用。
 */
export function clearQueuedTurnLocally(
  conversationId: string,
  queueId: string,
): QueuedTurnEntry | null {
  const removed = useQueuedTurnsStore
    .getState()
    .remove(conversationId, queueId);
  if (removed) {
    useConversationStore
      .getState()
      .removeMessage(removed.messageId, conversationId);
  }
  return removed;
}

/**
 * 按项取消 FIFO 排队（``POST …/queued-turns/{queue_id}/cancel``）。
 * 成功或 404（已不在队）→ 立刻本地清 UI，不依赖 live ``turn_queue_cancelled``
 * （Stop 后常无该事件）。SSE 仍作多端同步（幂等清）。
 * Stop ≠ 取消排队。
 */
export async function cancelQueuedTurn(
  conversationId: string,
  queueId: string,
): Promise<void> {
  try {
    await api.post(
      `/v1/conversations/${conversationId}/queued-turns/${queueId}/cancel`,
      {},
    );
    clearQueuedTurnLocally(conversationId, queueId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      clearQueuedTurnLocally(conversationId, queueId);
      return;
    }
    throw err;
  }
}
