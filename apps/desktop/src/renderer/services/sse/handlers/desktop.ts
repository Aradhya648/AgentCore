import { performDesktopNotify } from "@/services/desktopNotify";
import { performHostOp } from "@/services/hostOps";
import { performMcpOp } from "@/services/mcpOps";
import type {
  DesktopNotifyRequiredPayload,
  HostOpRequiredPayload,
  McpOpRequiredPayload,
  SSEEvent,
} from "@/types/events";
import type { DispatchContext } from "../types";

/** Desktop Client Tools: OS notify + Host face + MCP Client backfill. */
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
  if (event.type === "mcp_op_required") {
    void performMcpOp(
      event.payload as McpOpRequiredPayload,
      ctx.conversationId,
    );
    return true;
  }
  return false;
}
