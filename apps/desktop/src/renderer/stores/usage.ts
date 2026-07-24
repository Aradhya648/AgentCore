import {
  type TurnCost,
  type UsageSummary,
  getMessageCost,
  getUsageSummary,
} from "@/services/usage";
import { create } from "zustand";

/**
 * Account-level usage/cost state — the single front-end home for the FX rate,
 * the dashboard snapshot, and the per-turn payroll cache.
 *
 * `cnyPerUsd` is the one source every `formatCost` call reads, so the UI never
 * hard-codes the rate (§7.2): it is seeded from the backend default and refreshed
 * to the authoritative `settings.cny_per_usd` the moment `/usage/summary` loads.
 */

/** Fallback FX until `/usage/summary` is fetched — only avoids a NaN before the
 * first load. Must stay aligned with the backend default (`settings.cny_per_usd`,
 * 见 `config.py`); the fetched value supersedes it. */
const DEFAULT_CNY_PER_USD = 7.2;

// In-flight message-cost fetches, deduped outside the store so a re-render storm
// of hovers can't fire duplicate requests (and this churn never re-renders).
const inflightMessageCosts = new Set<string>();

interface UsageState {
  /** USD→CNY display rate; single source for every `formatCost` call. */
  cnyPerUsd: number;
  /** Last account-dashboard snapshot, or null before the first fetch. */
  summary: UsageSummary | null;
  loading: boolean;
  /** User-facing zh error for a failed summary fetch, or null. */
  error: string | null;
  /** Per-turn payroll snapshots from the ledger, keyed by message id — the
   * 回放/回落快照 source for a reloaded turn's cost (live turns carry their own
   * `message.cost`, so they never land here). */
  messageCosts: Record<string, TurnCost>;

  /** Fetch the account-dashboard summary and refresh the FX rate from it. */
  fetchSummary: () => Promise<void>;
  /** Lazily load + cache a turn's persisted payroll by message id (回落快照).
   * No-op if already cached or in flight; failures are swallowed (cost is
   * supplementary and must never break the chat). */
  loadMessageCost: (messageId: string) => Promise<void>;
}

export const useUsageStore = create<UsageState>((set, get) => ({
  cnyPerUsd: DEFAULT_CNY_PER_USD,
  summary: null,
  loading: false,
  error: null,
  messageCosts: {},

  fetchSummary: async () => {
    set({ loading: true, error: null });
    try {
      const summary = await getUsageSummary();
      set({ summary, cnyPerUsd: summary.cny_per_usd, loading: false });
    } catch {
      // A failed dashboard load must never break the chat (用量是附属呈现);
      // keep the last rate and surface a soft error for the dashboard view.
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
