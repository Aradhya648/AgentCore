import type { Execution } from "@/stores/execution";

/** Whether a turn has terminal trouble the boss can 救火 — failed / cancelled /
 * partial failure (completed with ≥1 failed run). */
export function isTurnRecoverable(
  execution: Execution | null | undefined,
): boolean {
  if (!execution) return false;
  if (execution.status === "failed" || execution.status === "cancelled")
    return true;
  return (
    execution.status === "completed" &&
    execution.runs.some((r) => r.status === "failed")
  );
}
