/**
 * Standing-task inbox badge (unacked awaiting_user + unacked failed).
 * Polled at the app shell so More 导航 stays live off the inbox page.
 */

import { countInboxBadge } from "@/services/standingTasks";
import { create } from "zustand";

const POLL_MS = 60_000;

interface StandingInboxState {
  badge: number;
  loading: boolean;
  refresh: () => Promise<void>;
  startPolling: () => () => void;
}

export const useStandingInboxStore = create<StandingInboxState>((set, get) => ({
  badge: 0,
  loading: false,

  refresh: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const badge = await countInboxBadge();
      set({ badge });
    } catch {
      // Soft-fail: keep last known badge (backend may not be up yet).
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
}));

export function useStandingInboxBadge(): number {
  return useStandingInboxStore((s) => s.badge);
}
