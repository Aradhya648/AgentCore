import type { CheckpointDecision } from "@/types/events";
import type { InteractionEntry } from "./types";

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

/**
 * Shared settlement fields for cold decision families (ask_user / team_preview /
 * plan_review). Replaces the duplicated status/decision/note branches that used
 * to live in parallel entryTo* adapters.
 */
export function mapEntryResolution(e: InteractionEntry): {
  status: "pending" | "resolved";
  decision: CheckpointDecision | null;
  note: string;
} {
  const resolved = e.status === "resolved";
  const r = e.resolution ?? {};
  return {
    status: resolved ? "resolved" : "pending",
    decision: resolved
      ? ((r.decision as CheckpointDecision | null | undefined) ?? null)
      : null,
    note: resolved ? str(r.note) : "",
  };
}
