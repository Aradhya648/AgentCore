import { ApiError } from "@/services/api";
import { resolveInteraction } from "@/services/interaction";
import type { BoardReadRequiredPayload } from "@/types/events";

/**
 * Desktop half of the whiteboard READ channel (AI协作白板.md §九 读图).
 *
 * The read counterpart of `boardOps.ts`. When the server-side `board_read` tool needs to
 * 看懂 a hand-drawn / screenshot subset of the user's selection, it streams a
 * `board_read_required` event; the open `WhiteboardCanvasPage` registers a reader (keyed by
 * board id) that rasterizes those elements through the self-built engine
 * (`engine.rasterizeElements`) to a PNG. We settle the paused read over the unified
 * interaction bridge (kind `client_tool`), so the live SSE turn resumes.
 *
 * Read-only: no CAS save (unlike `boardOps`, which mutates + persists) and no toast (nothing
 * visibly changes on the canvas). Failure policy mirrors `boardOps`: the channel must always
 * answer (or the server-side read only ends on its timeout). If the board's canvas is not
 * open (no reader registered), we resolve a clean error so the tool reports「画布未打开」
 * instead of the turn hanging. A stale request (404) is a no-op.
 */

/** What the canvas reader returns: a PNG (base64, no data: prefix) + its pixel size. */
export interface BoardRasterResult {
  pngBase64: string;
  w: number;
  h: number;
}

type BoardReader = (ids: string[]) => Promise<BoardRasterResult>;

// board_id → the open canvas's reader. At most one canvas per board is open, so the last
// registration wins; unregister is identity-checked so a stale unmount can't evict a newer
// mount's reader. Mirrors the applier registry in boardOps.ts.
const _readers = new Map<string, BoardReader>();

/** The open canvas registers its reader; returns an unregister for cleanup on unmount. */
export function registerBoardReader(
  boardId: string,
  reader: BoardReader,
): () => void {
  _readers.set(boardId, reader);
  return () => {
    if (_readers.get(boardId) === reader) _readers.delete(boardId);
  };
}

export async function performBoardRead(
  payload: BoardReadRequiredPayload,
  conversationId: string,
): Promise<void> {
  const result = await runBoardRead(payload);
  try {
    await resolveInteraction(conversationId, payload.request_id, {
      kind: "client_tool",
      ...result,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return; // stale — no-op
    console.error("[boardRead] 回填失败", err);
  }
}

type ClientToolResult =
  | { ok: true; value: BoardRasterResult }
  | { ok: false; error: { kind: string; detail: string } };

function readError(detail: string): ClientToolResult {
  return { ok: false, error: { kind: "BoardReadError", detail } };
}

async function runBoardRead(
  payload: BoardReadRequiredPayload,
): Promise<ClientToolResult> {
  const reader = _readers.get(payload.board_id);
  if (!reader) {
    return readError("该白板未在前台打开，无法读图");
  }
  try {
    const value = await reader(payload.ids ?? []);
    return { ok: true, value };
  } catch (e) {
    return readError(e instanceof Error ? e.message : String(e));
  }
}
