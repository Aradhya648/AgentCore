/**
 * Product notices (全局公告) — banner + inbox, polled at the app shell.
 * Distinct from IM unread and standing-task inbox badge.
 */

import {
  type ActiveNotice,
  dismissNotice,
  fetchActive,
} from "@/services/notices";
import { create } from "zustand";

const POLL_MS = 60_000;

interface ProductNoticesState {
  banner: ActiveNotice | null;
  inbox: ActiveNotice[];
  loading: boolean;
  refresh: () => Promise<void>;
  startPolling: () => () => void;
  dismiss: (id: string) => Promise<void>;
}

export const useProductNoticesStore = create<ProductNoticesState>(
  (set, get) => ({
    banner: null,
    inbox: [],
    loading: false,

    refresh: async () => {
      if (get().loading) return;
      set({ loading: true });
      try {
        const res = await fetchActive();
        set({
          banner: res.banner ?? null,
          inbox: Array.isArray(res.inbox) ? res.inbox : [],
        });
      } catch {
        // Soft-fail: keep last known notices (backend may not be up yet).
      } finally {
        set({ loading: false });
      }
    },

    startPolling: () => {
      void get().refresh();
      const id = window.setInterval(() => {
        void get().refresh();
      }, POLL_MS);
      return () => window.clearInterval(id);
    },

    dismiss: async (id: string) => {
      await dismissNotice(id);
      await get().refresh();
    },
  }),
);

/** Undismissed inbox count for More nav badge. */
export function useProductNoticesUndismissedCount(): number {
  return useProductNoticesStore(
    (s) => s.inbox.filter((n) => !n.dismissed).length,
  );
}
