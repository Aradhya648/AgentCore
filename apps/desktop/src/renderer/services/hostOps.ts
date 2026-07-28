import { ApiError } from "@/services/api";
import { resolveInteraction } from "@/services/interaction";
import type { HostOpRequiredPayload } from "@/types/events";
import type { HostOpResult } from "@shared/host-contract";

/**
 * Desktop half of the Host ClientTool channel.
 *
 * After the server suspends and streams ``host_op_required``, we run the op in
 * the main process and settle over the unified interaction bridge
 * (kind ``client_tool``).
 */
export async function performHostOp(
  payload: HostOpRequiredPayload,
  conversationId: string,
): Promise<void> {
  const result = await runHostOp(payload);
  try {
    await resolveInteraction(conversationId, payload.request_id, {
      kind: "client_tool",
      ...result,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return;
    console.error("[hostOps] 回填失败", err);
  }
}

async function runHostOp(payload: HostOpRequiredPayload): Promise<HostOpResult> {
  const api = typeof window !== "undefined" ? window.hostApi : undefined;
  if (!api?.runOp) {
    return {
      ok: false,
      error: {
        kind: "HostOpError",
        detail: "非桌面环境，无法履行本机 Host 操作",
      },
    };
  }
  try {
    return await api.runOp({
      op: payload.op,
      args: (payload.args ?? {}) as Record<string, unknown>,
    });
  } catch (e) {
    return {
      ok: false,
      error: {
        kind: "HostOpError",
        detail: e instanceof Error ? e.message : String(e),
      },
    };
  }
}
