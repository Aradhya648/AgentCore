import { api } from "@/services/api";

/**
 * Ask the backend to stop a conversation's in-flight turn (执行与请求解耦 C1 · slice 1a).
 *
 * A client disconnect no longer cancels a server turn — it finishes and persists
 * in the background (so a long turn is never lost to a dropped connection, 案例 1).
 * The 停止 button therefore must explicitly ask the server to cancel the detached
 * run; aborting the local fetch alone would leave it running and billing.
 *
 * Returns whether a live run was actually signalled (false when nothing was
 * running, e.g. a sidecar/local turn or an already-finished one). Failures
 * propagate to the caller so the UI can surface a visible toast (不再静默吞掉).
 */
export async function stopConversation(
  conversationId: string,
): Promise<boolean> {
  const res = await api.post<{ stopped: boolean }>(
    `/v1/conversations/${conversationId}/stop`,
  );
  return res.stopped;
}
