/** 画布放大态 per-turn 视图偏好（群聊 / 对比 / 协作图 …），按对话×回合记忆。 */

import { registerConversationUiClearer, uiGet, uiSet } from "@/lib/uiStorage";

export type CanvasTurnView = "room" | "graph" | "compare";

const STORAGE_KEY = "canvas-turn-views";

const VALID: ReadonlySet<CanvasTurnView> = new Set([
  "room",
  "graph",
  "compare",
]);

function entryKey(conversationId: string, turnId: string): string {
  return `${conversationId}:${turnId}`;
}

function loadAll(): Record<string, CanvasTurnView> {
  const parsed = uiGet<Record<string, unknown>>(STORAGE_KEY);
  if (!parsed || typeof parsed !== "object") return {};
  const out: Record<string, CanvasTurnView> = {};
  for (const [k, v] of Object.entries(parsed)) {
    if (typeof v === "string" && VALID.has(v as CanvasTurnView)) {
      out[k] = v as CanvasTurnView;
    }
  }
  return out;
}

function saveAll(views: Record<string, CanvasTurnView>): void {
  if (Object.keys(views).length === 0) uiSet(STORAGE_KEY, undefined);
  else uiSet(STORAGE_KEY, views);
}

export function loadCanvasTurnView(
  conversationId: string,
  turnId: string,
): CanvasTurnView | null {
  return loadAll()[entryKey(conversationId, turnId)] ?? null;
}

export function persistCanvasTurnView(
  conversationId: string,
  turnId: string,
  view: CanvasTurnView,
): void {
  const all = loadAll();
  all[entryKey(conversationId, turnId)] = view;
  saveAll(all);
}

registerConversationUiClearer((conversationId) => {
  const all = loadAll();
  const prefix = `${conversationId}:`;
  let changed = false;
  for (const key of Object.keys(all)) {
    if (key.startsWith(prefix)) {
      delete all[key];
      changed = true;
    }
  }
  if (changed) saveAll(all);
});

/** Pick a saved view when still valid for this turn's tab strip, else the natural default. */
export function resolveCanvasTurnView(
  saved: CanvasTurnView | null,
  naturalDefault: CanvasTurnView,
  available: ReadonlySet<CanvasTurnView>,
): CanvasTurnView {
  if (saved && available.has(saved)) return saved;
  return naturalDefault;
}
