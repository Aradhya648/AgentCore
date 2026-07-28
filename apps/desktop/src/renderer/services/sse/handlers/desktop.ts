import { performDesktopNotify } from "@/services/desktopNotify";
import { performHostOp } from "@/services/hostOps";
import type {
  DesktopNotifyRequiredPayload,
  HostOpRequiredPayload,
  SSEEvent,
} from "@/types/events";
import type { DispatchContext } from "../types";

/** Desktop Client Tools: OS notify + Host face backfill. */
export function handleDesktopEvent(
  event: SSEEvent,
  ctx: DispatchContext,
): boolean {
  if (event.type === "desktop_notify_required") {
    void performDesktopNotify(
      event.payload as DesktopNotifyRequiredPayload,
      ctx.conversationId,
    );
    return true;
  }
  if (event.type === "host_op_required") {
    void performHostOp(
      event.payload as HostOpRequiredPayload,
      ctx.conversationId,
    );
    return true;
  }
  return false;
}
