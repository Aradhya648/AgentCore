import { performDesktopNotify } from "@/services/desktopNotify";
import type { DesktopNotifyRequiredPayload, SSEEvent } from "@/types/events";
import type { DispatchContext } from "../types";

/** Agent ``desktop_notify`` tool: show an OS notification after user approval. */
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
  return false;
}
