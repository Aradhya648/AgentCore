import { notifyInfo } from "@/lib/toast";
import { fulfillClientToolOnce } from "@/services/clientToolFulfill";
import type { BoardOp, BoardOpRequiredPayload } from "@/types/events";

/**
 * Desktop half of the whiteboard op channel (AI协作白板.md §六 M2).
 *
 * When the server-side `board_ops` tool needs to draw on the user's open canvas it
 * streams a `board_op_required` event; the open `WhiteboardCanvasPage` registers an
 * applier (keyed by board id) that applies the ops through the self-built engine
 * (`whiteboard/ops.ts`), CAS-saves, and reports back. We settle the paused op over the
 * unified interaction bridge (kind `client_tool`), so the live SSE turn resumes.
 *
 * Failure policy: the channel must always answer (or the server-side op only ends on
 * its timeout). If the board's canvas is not open (no applier registered), we resolve a
 * clean error so the tool reports「画布未打开」instead of the turn hanging. A stale
 * request (404) is a no-op.
 *
 * Same ``request_id`` is de-duplicated in-process so attach rehang does not
 * re-apply board ops.
 */

/** What the canvas applier returns after applying a batch (rides the resolve回执). */
export interface BoardApplyResult {
  applied: number;
  created: string[];
  version: number;
}

type BoardApplier = (ops: BoardOp[]) => Promise<BoardApplyResult>;

// board_id → the open canvas's applier. At most one canvas per board is open, so the
// last registration wins; unregister is identity-checked so a stale unmount can't evict
// a newer mount's applier.
const _appliers = new Map<string, BoardApplier>();

/** The open canvas registers its applier; returns an unregister for cleanup on unmount. */
export function registerBoardApplier(
  boardId: string,
  applier: BoardApplier,
): () => void {
  _appliers.set(boardId, applier);
  return () => {
    if (_appliers.get(boardId) === applier) _appliers.delete(boardId);
  };
}

export async function performBoardOp(
  payload: BoardOpRequiredPayload,
  conversationId: string,
): Promise<void> {
  await fulfillClientToolOnce({
    requestId: payload.request_id,
    conversationId,
    logLabel: "boardOps",
    perform: async () => {
      const result = await runBoardOps(payload);
      // Visible feedback that the AI just drew (the canvas has no chat surface): the model's
      // one-line summary, or a generic notice. Only on success — a failure settles silently
      // and the tool result tells the model the ops didn't land.
      if (result.ok) {
        notifyInfo(payload.summary?.trim() || "AI 已更新白板");
      }
      return result;
    },
  });
}

type ClientToolResult =
  | { ok: true; value: BoardApplyResult }
  | { ok: false; error: { kind: string; detail: string } };

function boardError(detail: string): ClientToolResult {
  return { ok: false, error: { kind: "BoardOpError", detail } };
}

async function runBoardOps(
  payload: BoardOpRequiredPayload,
): Promise<ClientToolResult> {
  const applier = _appliers.get(payload.board_id);
  if (!applier) {
    return boardError("该白板未在前台打开，无法作画");
  }
  try {
    const value = await applier(payload.ops ?? []);
    return { ok: true, value };
  } catch (e) {
    return boardError(e instanceof Error ? e.message : String(e));
  }
}
