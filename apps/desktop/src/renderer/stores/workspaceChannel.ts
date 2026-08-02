import { create } from "zustand";

/**
 * Soft banner when a local workspace file op hits AbortSignal / 活性挂起
 * (channel liveness). Hint-only — does not block open/write or rebuild roots.
 * ``probe_exec`` language probes must not set this (they only trim advertise).
 */
interface WorkspaceChannelState {
  /** True while the soft “本地文件通道未就绪” banner should show. */
  notReady: boolean;
  /** Session dismiss; a later real file-op hang can show again. */
  markNotReady: () => void;
  dismiss: () => void;
}

export const useWorkspaceChannelStore = create<WorkspaceChannelState>(
  (set) => ({
    notReady: false,
    markNotReady: () => set({ notReady: true }),
    dismiss: () => set({ notReady: false }),
  }),
);
