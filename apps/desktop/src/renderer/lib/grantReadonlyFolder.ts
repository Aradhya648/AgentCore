import { hasLocalFiles } from "@/lib/capabilities";
import { ApiError, api } from "@/services/api";
import type { FsRoot } from "@shared/ipc-contract";

export type GrantReadonlyResult =
  | {
      ok: true;
      root: FsRoot;
      alias: string;
      namespace: string;
    }
  | { ok: false; reason: "cancelled" | "unavailable" }
  | { ok: false; reason: "error"; message: string };

function describeGrantError(e: unknown): string {
  if (e instanceof ApiError && e.status === 404) {
    return "对话不存在或无权访问";
  }
  return e instanceof Error ? e.message : "授权失败，请重试";
}

/** Answer text so the CEO sees which folder was granted (no absolute path). */
export function formatGrantReadonlyFolderAnswer(
  optionLabel: string,
  folderName: string,
  namespace: string,
): string {
  return `${optionLabel}（${folderName} → ${namespace}；只读、仅本次对话、可撤销）`;
}

/**
 * OS folder picker → session read-only root → POST grant to server.
 * Does not change workspace binding.
 */
export async function pickAndGrantReadonlyFolder(
  conversationId: string,
): Promise<GrantReadonlyResult> {
  if (!hasLocalFiles() || !window.fsApi?.grantSessionReadonlyRoot) {
    return { ok: false, reason: "unavailable" };
  }
  try {
    const root = await window.fsApi.grantSessionReadonlyRoot(conversationId);
    if (!root) return { ok: false, reason: "cancelled" };
    try {
      const body = await api.post<{
        grant: { alias: string; namespace: string };
      }>(`/v1/conversations/${conversationId}/workspace/external-grants`, {
        root_id: root.id,
        label: root.name,
        alias_hint: root.alias ?? root.name,
      });
      return {
        ok: true,
        root,
        alias: body.grant.alias,
        namespace: body.grant.namespace,
      };
    } catch (e) {
      await window.fsApi.revokeSessionReadonlyRoot?.(conversationId, root.id);
      throw e;
    }
  } catch (e) {
    return { ok: false, reason: "error", message: describeGrantError(e) };
  }
}
