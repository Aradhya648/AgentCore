import { fulfillClientToolOnce } from "@/services/clientToolFulfill";
import type { HostOpRequiredPayload } from "@/types/events";
import type { HostOpResult } from "@shared/host-contract";

/**
 * Desktop half of the Host ClientTool channel.
 *
 * After the server suspends and streams ``host_op_required``, we run the op in
 * the main process and settle over the unified interaction bridge
 * (kind ``client_tool``). Same ``request_id`` is de-duplicated in-process so
 * attach rehang does not re-run host side effects (e.g. shell).
 */
export async function performHostOp(
  payload: HostOpRequiredPayload,
  conversationId: string,
): Promise<void> {
  await fulfillClientToolOnce({
    requestId: payload.request_id,
    conversationId,
    logLabel: "hostOps",
    perform: () => runHostOp(payload),
  });
}

async function runHostOp(
  payload: HostOpRequiredPayload,
): Promise<HostOpResult> {
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
