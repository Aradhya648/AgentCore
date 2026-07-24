import { performWorkspaceOp } from "@/services/workspaceOps";
import type { SSEEvent, WorkspaceOpRequiredPayload } from "@/types/events";
import type { DispatchContext } from "../types";

export function handleWorkspaceEvent(
  event: SSEEvent,
  ctx: DispatchContext,
): boolean {
  switch (event.type) {
    case "workspace_op_required": {
      void performWorkspaceOp(
        event.payload as WorkspaceOpRequiredPayload,
        ctx.conversationId,
      );
      return true;
    }
    default:
      return false;
  }
}
