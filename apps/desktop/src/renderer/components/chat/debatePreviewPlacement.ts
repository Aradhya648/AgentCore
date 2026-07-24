import type { TeamPreviewDisplay } from "@/stores/conversation";

/**
 * True once the team has actually started work: any run left the never-started
 * states (`pending`, or terminal `skipped` from finalize before a start).
 * Gates the inline graph so team_preview hang / stop-before-start stay graph-less;
 * plan_review mid-wave pause (completed nodes exist) still shows the graph.
 */
export function teamHasStartedRuns(
  runs: readonly { status: string }[],
): boolean {
  return runs.some((r) => r.status !== "pending" && r.status !== "skipped");
}

/**
 * Shared visibility for resolved team_preview content (debate or delegate):
 * when true → hide standalone ResolvedTeamPreview, host details in InlineTeamGraph;
 * when false → keep the standalone card (pending, or resolved-but-graph-absent).
 */
export function shouldHostPreviewInGraph(
  preview: Pick<TeamPreviewDisplay, "status"> | null | undefined,
  runs: readonly { status: string }[] | null | undefined,
): boolean {
  if (!preview || !runs) return false;
  return preview.status === "resolved" && teamHasStartedRuns(runs);
}
