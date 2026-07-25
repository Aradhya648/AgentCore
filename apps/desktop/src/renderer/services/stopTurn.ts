import { api } from "@/services/api";
import { getActiveSidecarTarget } from "@/services/sidecarRouting";

/**
 * Ask the engine to stop a conversation's in-flight turn (执行与请求解耦 C1 · slice 1a).
 *
 * A client disconnect no longer cancels a server turn — it finishes and persists
 * in the background (so a long turn is never lost to a dropped connection, 案例 1).
 * The 停止 button therefore must explicitly ask the engine to cancel; aborting the
 * local fetch alone would leave it running and billing.
 *
 * Routing mirrors ``resolveInteraction`` / ``submitRunRedirect``:
 * - **Local (sidecar) turn** → ``sidecarApi.cancel`` (cloud ``POST /stop`` cannot
 *   reach the in-process turn / coordination session).
 * - **Cloud turn** → ``POST …/stop``.
 *
 * Returns whether a live run was actually signalled (false when nothing was
 * running / already finished). Failures propagate so the UI can surface a
 * visible toast / retry (不再静默吞掉).
 */
export async function stopConversation(
  conversationId: string,
): Promise<boolean> {
  const sidecarTarget = getActiveSidecarTarget(conversationId);
  if (sidecarTarget) {
    const turnId = sidecarTarget.turnId;
    if (!turnId) {
      throw new Error("本地回合标识缺失，无法停止");
    }
    await window.sidecarApi.cancel({
      rootId: sidecarTarget.rootId,
      subpath: sidecarTarget.subpath,
      turnId,
      conversationId,
    });
    // Sidecar cancel is fire-and-confirm via message_end(cancelled); RPC ack means
    // the signal was delivered (idempotent when the turn already settled).
    return true;
  }
  const res = await api.post<{ stopped: boolean }>(
    `/v1/conversations/${conversationId}/stop`,
  );
  return res.stopped;
}
