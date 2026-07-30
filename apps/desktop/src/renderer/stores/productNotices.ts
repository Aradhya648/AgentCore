/**
 * Product notices (全局公告) — banner + inbox, polled at the app shell.
 * Distinct from IM unread and standing-task inbox badge.
 *
 * Banner close is always available:
 * - ``once`` → server dismiss (不回潮)
 * - ``never`` → session snooze banner only (inbox 仍可见；刷新会话后横幅可再出现)
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
  /** Banner ids snoozed for this session (``dismiss_policy=never``). */
  sessionSnoozed: string[];
  loading: boolean;
  refresh: () => Promise<void>;
  startPolling: () => () => void;
  dismiss: (id: string) => Promise<void>;
}

function pickBanner(
  banner: ActiveNotice | null | undefined,
  snoozed: string[],
): ActiveNotice | null {
  if (!banner) return null;
  if (snoozed.includes(banner.id)) return null;
  return banner;
}

export const useProductNoticesStore = create<ProductNoticesState>(
  (set, get) => ({
    banner: null,
    inbox: [],
    sessionSnoozed: [],
    loading: false,

    refresh: async () => {
      if (get().loading) return;
      set({ loading: true });
      try {
        const res = await fetchActive();
        const snoozed = get().sessionSnoozed;
        set({
          banner: pickBanner(res.banner, snoozed),
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
      const { banner, inbox, sessionSnoozed } = get();
      const notice =
        banner?.id === id ? banner : (inbox.find((n) => n.id === id) ?? null);

      // Optimistic: hide banner immediately.
      if (banner?.id === id) {
        set({ banner: null });
      }

      // ``never``: session-snooze banner only (API would 409).
      if (notice?.dismiss_policy === "never") {
        if (!sessionSnoozed.includes(id)) {
          set({ sessionSnoozed: [...sessionSnoozed, id] });
        }
        return;
      }

      try {
        await dismissNotice(id);
      } catch {
        // Soft-fail: still refresh so server truth wins.
      }
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
