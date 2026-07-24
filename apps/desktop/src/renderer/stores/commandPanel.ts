import { create } from "zustand";

/**
 * Bridge for the 指挥台 (war-room command tab), hosted as a fixed second tab in the
 * unified right side panel (前端UX设计.md §6.2 · §十) — after 「工作区」, before any
 * closable run/content detail tabs.
 *
 * Turn focus is a canvas concept, so {@link
 * import("../components/graph/ConversationCanvas")} publishes two things here:
 *  - `active`: the canvas view is mounted, so the 指挥台 tab MAY appear (chat mode
 *    keeps decisions inline in the message stream, so it stays false there);
 *  - `focusedMessageId`: the focused team turn whose turn-level cards (ask_user /
 *    plan_review / 工作者上报) render — null when no team turn is focused
 *    (conversation-level approval / resume / 救火 / 后台云端任务 still surface).
 *
 * The tab — rendered by {@link import("../components/layout/SidePanel")} — reads
 * these and derives everything else live from the execution / approval / resume /
 * background stores (single data source, no snapshot copy).
 */
interface CommandPanelState {
  /** Canvas view is mounted — gates the 指挥台 tab (chat mode keeps decisions inline). */
  active: boolean;
  /** Focused team turn's assistant message id (turn-level card scope); null = none. */
  focusedMessageId: string | null;
  /** Canvas mount/unmount toggles this; leaving canvas also clears the focus. */
  setActive: (active: boolean) => void;
  setFocused: (messageId: string | null) => void;
}

export const useCommandPanelStore = create<CommandPanelState>((set) => ({
  active: false,
  focusedMessageId: null,
  setActive: (active) =>
    set(active ? { active: true } : { active: false, focusedMessageId: null }),
  setFocused: (focusedMessageId) => set({ focusedMessageId }),
}));
