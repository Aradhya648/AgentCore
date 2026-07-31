import type { CheckpointIntent } from "@/types/events";

/** Normalize wire/recovery `intent` — unknown / missing → decision (zero-regression default). */
export function parseCheckpointIntent(raw: unknown): CheckpointIntent {
  if (
    raw === "kickoff" ||
    raw === "decision" ||
    raw === "proposal_pick" ||
    raw === "risk_ack" ||
    raw === "organize_plan" ||
    raw === "daily_review"
  ) {
    return raw;
  }
  return "decision";
}
