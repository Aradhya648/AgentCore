import type { ExecutionStatus, TeamNote } from "@/stores/execution";

/**
 * Canvas / chat shared rule for whether the team-notes wall starts open.
 * Running turns with at least one `active` note expand by default; finished /
 * stopped turns stay collapsed to a「便签 N」signal.
 */
export function teamNotesDefaultExpanded(
  status: ExecutionStatus | null | undefined,
  notes: readonly TeamNote[],
): boolean {
  if (notes.length === 0) return false;
  if (status !== "running") return false;
  return notes.some((n) => n.status === "active");
}
