import { hasLocalFiles } from "@/lib/capabilities";
import { api } from "@/services/api";

/**
 * Revoke one conversation external grant on both sides: DELETE server row, then
 * drop the desktop session root (and its persisted fs-session-grants entry).
 */
export async function revokeExternalGrant(
  conversationId: string,
  rootId: string,
): Promise<boolean> {
  const qs = new URLSearchParams({ root_id: rootId });
  try {
    await api.delete(
      `/v1/conversations/${conversationId}/workspace/external-grants?${qs}`,
    );
  } catch {
    // Still clear local — server may already have revoked / 404.
  }
  if (!hasLocalFiles() || !window.fsApi?.revokeSessionReadonlyRoot) {
    return false;
  }
  return window.fsApi.revokeSessionReadonlyRoot(conversationId, rootId);
}
