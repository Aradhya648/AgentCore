// Internal drag payload (a source-relative path + its source id). A custom MIME
// distinguishes it from an OS file drag (which carries `Files` → "upload"); the
// source id scopes the move so a node can't be dropped onto a different source.
export const DRAG_MIME = "application/x-agentcore-file";

export interface DragPayload {
  sourceId: string;
  path: string;
}

export function parseDragPayload(raw: string): DragPayload | null {
  try {
    const p: unknown = JSON.parse(raw);
    if (
      p &&
      typeof p === "object" &&
      typeof (p as DragPayload).sourceId === "string" &&
      typeof (p as DragPayload).path === "string"
    ) {
      return p as DragPayload;
    }
  } catch {
    /* not our payload */
  }
  return null;
}
