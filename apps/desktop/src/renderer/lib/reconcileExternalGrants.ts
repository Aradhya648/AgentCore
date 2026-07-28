import { hasLocalFiles } from "@/lib/capabilities";
import { api } from "@/services/api";
import type { FsRoot } from "@shared/ipc-contract";

type ServerGrant = {
  alias: string;
  root_id: string;
  label: string;
  mode?: "readonly" | "organize";
};

/**
 * Align desktop session roots with server conversation_external_grants.
 * Absolute paths never leave the desktop — only root_id / alias / mode.
 *
 * - Desktop has root, server missing → POST（补登记，例如 API 重启前的旧内存态）
 * - Server has root_id, desktop missing → **不** DELETE：服务端是对话级真相，
 *   本机无路径只表示本设备无法履约（换机 / 清过 userData）；误删会打掉他机授权。
 *   用户显式撤销走 revoke API。
 */
export async function reconcileExternalGrants(
  conversationId: string,
): Promise<void> {
  if (!hasLocalFiles() || !window.fsApi?.listSessionReadonlyRoots) return;

  let local: FsRoot[] = [];
  try {
    local = await window.fsApi.listSessionReadonlyRoots(conversationId);
  } catch {
    return;
  }

  let remote: ServerGrant[] = [];
  try {
    const res = await api.get<{ data: ServerGrant[] }>(
      `/v1/conversations/${conversationId}/workspace/external-grants`,
    );
    remote = res.data ?? [];
  } catch {
    return;
  }

  const remoteByRoot = new Map(remote.map((g) => [g.root_id, g]));

  for (const root of local) {
    if (remoteByRoot.has(root.id)) continue;
    try {
      await api.post(
        `/v1/conversations/${conversationId}/workspace/external-grants`,
        {
          root_id: root.id,
          label: root.name,
          alias_hint: root.alias ?? root.name,
          mode: root.mode === "organize" ? "organize" : "readonly",
        },
      );
    } catch {
      // Best-effort; next open retries.
    }
  }
}
