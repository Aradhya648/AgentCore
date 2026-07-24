/**
 * D2 projection: turns that settled a decision then lost live execution.
 * Hydrated from recovery.interruptedAfterDecision (journal fold), not unsynced.
 */
import type { SidecarInterruptedAfterDecision } from "@shared/sidecar-contract";
import { create } from "zustand";

interface InterruptedAfterDecisionState {
  byConversation: Record<string, SidecarInterruptedAfterDecision[]>;
  setForConversation: (
    conversationId: string,
    items: SidecarInterruptedAfterDecision[],
  ) => void;
  remove: (conversationId: string, messageId: string) => void;
  clear: () => void;
}

export const useInterruptedAfterDecisionStore =
  create<InterruptedAfterDecisionState>((set) => ({
    byConversation: {},
    setForConversation: (conversationId, items) =>
      set((s) => ({
        byConversation: { ...s.byConversation, [conversationId]: items },
      })),
    remove: (conversationId, messageId) =>
      set((s) => ({
        byConversation: {
          ...s.byConversation,
          [conversationId]: (s.byConversation[conversationId] ?? []).filter(
            (i) => i.messageId !== messageId,
          ),
        },
      })),
    clear: () => set({ byConversation: {} }),
  }));
