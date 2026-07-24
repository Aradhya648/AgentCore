import { create } from "zustand";

/**
 * Ambient backend connectivity, sampled by a lightweight `/readyz` heartbeat
 * (see `services/serverHealth`). This is the "can I reach the server *right now*"
 * signal the composer shows so the user knows connectivity **before** sending —
 * distinct from the auth store's `unavailable`, which is the hard, full-screen
 * outage takeover the AuthGate raises reactively on a failed request.
 *
 * - `checking`: the first probe hasn't resolved yet (startup) — never flashed as
 *   "offline" so a healthy session doesn't blink red on load.
 * - `online` / `offline`: the last probe's verdict.
 */
export type ServerConn = "checking" | "online" | "offline";

interface ServerHealthState {
  status: ServerConn;
  /** Epoch ms of the last successful probe, or null if never reached. */
  lastOkAt: number | null;
  /** User-facing reason while offline (from `diagnoseOutage`), else null. */
  reason: string | null;
  /** True briefly right after recovering, so the chip can flash "已恢复连接". */
  justRecovered: boolean;
  markOnline: () => void;
  markOffline: (reason: string | null) => void;
  clearRecovered: () => void;
}

export const useServerHealthStore = create<ServerHealthState>((set, get) => ({
  status: "checking",
  lastOkAt: null,
  reason: null,
  justRecovered: false,
  markOnline: () =>
    set({
      status: "online",
      lastOkAt: Date.now(),
      reason: null,
      // Only celebrate a recovery if we were actually offline before.
      justRecovered: get().status === "offline",
    }),
  markOffline: (reason) => set({ status: "offline", reason }),
  clearRecovered: () => set({ justRecovered: false }),
}));
