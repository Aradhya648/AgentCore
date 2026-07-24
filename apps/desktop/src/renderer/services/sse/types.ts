import type { ResumeOrigin } from "@/stores/pausedTurns";

/** Per-turn dispatch context passed to every SSE handler. */
export interface DispatchContext {
  conversationId: string;
  /** Which transport delivered this event — set at the dispatch entry (HTTP SSE vs sidecar IPC). */
  source: ResumeOrigin;
}
