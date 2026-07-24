import { performBoardOp } from "@/services/boardOps";
import { performBoardRead } from "@/services/boardRead";
import type {
  BoardOpRequiredPayload,
  BoardReadRequiredPayload,
  SSEEvent,
} from "@/types/events";
import type { DispatchContext } from "../types";

/** AI 协作白板 (AI协作白板.md §六 M2 + §九): the server asks the open canvas to apply a
 * board-op batch (`board_op_required`) or rasterize a subset for the vision reader
 * (`board_read_required`); we run it against the registered applier / reader and settle the
 * paused interaction so the turn resumes (fire-and-forget — `performBoardOp` /
 * `performBoardRead` always answer, even on a closed canvas). */
export function handleBoardEvent(
  event: SSEEvent,
  ctx: DispatchContext,
): boolean {
  if (event.type === "board_op_required") {
    void performBoardOp(
      event.payload as BoardOpRequiredPayload,
      ctx.conversationId,
    );
    return true;
  }
  if (event.type === "board_read_required") {
    void performBoardRead(
      event.payload as BoardReadRequiredPayload,
      ctx.conversationId,
    );
    return true;
  }
  return false;
}
