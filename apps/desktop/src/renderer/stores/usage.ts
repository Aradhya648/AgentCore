import {
  type TurnCost,
  type UsageSummary,
  getMessageCost,
  getUsageSummary,
} from "@/services/usage";
import { create } from "zustand";

/**
 * Account-level usage/cost state — dashboard snapshot + per-turn payroll cache.
 *
 * Money is nano-CNY end-to-end; the UI formats ¥ as `nano / 1e9` (no FX).
 */

// In-flight message-cost fetches, deduped outside the store so a re-render storm
// of hovers can't fire duplicate requests (and this churn never re-renders).
const inflightMessageCosts = new Set<string>();

interface UsageState {
  /** Last account-dashboard snapshot, or null before the first fetch. */
  summary: UsageSummary | null;
  loading: boolean;
  /** User-facing zh error for a failed summary fetch, or null. */
  error: string | null;
  /** Per-turn payroll snapshots from the ledger, keyed by message id — the
   * 回放/回落快照 source for a reloaded turn's cost (live turns carry their own
   * `message.cost`, so they never land here). */
  messageCosts: Record<string, TurnCost>;

  /** Fetch the account-dashboard summary. */
  fetchSummary: () => Promise<void>;
  /** Lazily load + cache a turn's persisted payroll by message id (回落快照).
   * No-op if already cached or in flight; failures are swallowed (cost is
   * supplementary and must never break the chat). */
  loadMessageCost: (messageId: string) => Promise<void>;
}

export const useUsageStore = create<UsageState>((set, get) => ({
  summary: null,
  loading: false,
  error: null,
  messageCosts: {},

  fetchSummary: async () => {
    set({ loading: true, error: null });
    try {
      const summary = await getUsageSummary();
      set({ summary, loading: false });
    } catch {
      // A failed dashboard load must never break the chat (用量是附属呈现);
      // surface a soft error for the dashboard view.
      set({ loading: false, error: "用量加载失败，请重试" });
    }
  },

  loadMessageCost: async (messageId) => {
    if (!messageId) return;
    if (get().messageCosts[messageId] || inflightMessageCosts.has(messageId)) {
      return;
    }
    inflightMessageCosts.add(messageId);
    try {
      const turn = await getMessageCost(messageId);
      set((s) => ({ messageCosts: { ...s.messageCosts, [messageId]: turn } }));
    } catch {
      /* supplementary — a missing payroll just leaves the row without ¥ */
    } finally {
      inflightMessageCosts.delete(messageId);
    }
  },
}));
