import { api } from "@/services/api";
import { getActiveSidecarTarget } from "@/services/sidecarRouting";

/**
 * Ask the engine to cancel a conversation's in-flight turn.
 *
 * A client disconnect no longer cancels a server turn — it finishes and persists
 * in the background. The 停止 button therefore must explicitly ask the engine;
 * aborting the local fetch alone would leave it running and billing.
 *
 * Routing mirrors ``resolveInteraction`` / ``submitRunRedirect``:
 * - **Local (sidecar) turn** → ``sidecarApi.cancel`` (cloud ``POST /stop`` cannot
 *   reach the in-process turn / coordination session).
 * - **Cloud turn** → ``POST …/stop``.
 *
 * Failures propagate so the UI can surface a visible toast / retry.
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
      reason: "user_stop",
    });
    return true;
  }
  const res = await api.post<{ stopped: boolean }>(
    `/v1/conversations/${conversationId}/stop`,
  );
  return res.stopped;
}
