import type { Execution } from "@/stores/execution";

/**
 * Scheduling helpers from `batch_metrics` / `execution.batches[].timeline`.
 * Graph toolbar metrics chip + gate (≥2 dispatched workers). Temporal truth for
 * diagnosis lives in SchedulingDiag — collaboration-graph timeline layout was removed.
 */

/** Whether a turn has enough parallel-execution data for the metrics chip: ≥2 dispatched
 * worker runs across scheduler segments (a single-worker one-bar timeline is trivial). */
export function hasParallelTimeline(execution: Execution): boolean {
  return execution.batches.reduce((n, b) => n + b.timeline.length, 0) >= 2;
}

/** One-line scheduling summary for the graph toolbar chip. */
export function parallelTimelineMetricsSummary(
  execution: Execution,
): string | null {
  const batches = execution.batches.filter((b) => b.timeline.length > 0);
  if (batches.length === 0) return null;
  const peak = Math.max(...batches.map((b) => b.peakRunning));
  const wallMs = batches.reduce((s, b) => s + b.wallMs, 0);
  const starved = batches.reduce((s, b) => s + b.slotStarved, 0);
  const parts = [`峰值 ${peak}`, fmtMs(wallMs)];
  if (starved > 0) parts.splice(1, 0, `串行 ${starved}`);
  if (batches.length > 1) parts.unshift(`${batches.length} 批次`);
  return parts.join(" · ");
}

/** Compact ms → 「N毫秒」/「N.N秒」for the bar labels (sub-second stays in ms so a fast
 * tool call doesn't collapse to 0.0秒). */
export function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
