import { create } from "zustand";

/** 同对话 FIFO 排队项（live · turn_queued；进程内，重启丢）。 */
export interface QueuedTurnEntry {
  queueId: string;
  conversationId: string;
  /** 主时间线乐观用户气泡 id（取消时移除）。 */
  messageId: string;
  content: string;
  position: number;
  queueDepth: number;
  degradedFrom?: "steer";
}

interface QueuedTurnsState {
  byConversation: Record<string, QueuedTurnEntry[]>;
  upsert: (entry: QueuedTurnEntry) => void;
  remove: (conversationId: string, queueId: string) => QueuedTurnEntry | null;
  clearConversation: (conversationId: string) => void;
  list: (conversationId: string | null | undefined) => QueuedTurnEntry[];
}

export const useQueuedTurnsStore = create<QueuedTurnsState>((set, get) => ({
  byConversation: {},

  upsert: (entry) =>
    set((state) => {
      const prev = state.byConversation[entry.conversationId] ?? [];
      const without = prev.filter((e) => e.queueId !== entry.queueId);
      return {
        byConversation: {
          ...state.byConversation,
          [entry.conversationId]: [...without, entry].sort(
            (a, b) => a.position - b.position,
          ),
        },
      };
    }),

  remove: (conversationId, queueId) => {
    const prev = get().byConversation[conversationId] ?? [];
    const hit = prev.find((e) => e.queueId === queueId) ?? null;
    if (!hit) return null;
    set((state) => {
      const next = (state.byConversation[conversationId] ?? []).filter(
        (e) => e.queueId !== queueId,
      );
      const byConversation = { ...state.byConversation };
      if (next.length === 0) delete byConversation[conversationId];
      else byConversation[conversationId] = next;
      return { byConversation };
    });
    return hit;
  },

  clearConversation: (conversationId) =>
    set((state) => {
      if (!state.byConversation[conversationId]) return state;
      const byConversation = { ...state.byConversation };
      delete byConversation[conversationId];
      return { byConversation };
    }),

  list: (conversationId) =>
    conversationId ? (get().byConversation[conversationId] ?? []) : [],
}));

export function useQueuedTurns(
  conversationId: string | null | undefined,
): QueuedTurnEntry[] {
  return useQueuedTurnsStore((s) =>
    conversationId ? (s.byConversation[conversationId] ?? EMPTY) : EMPTY,
  );
}

const EMPTY: QueuedTurnEntry[] = [];
