import type { BatchMetricsSnapshot, Execution } from "@/stores/execution";
/**
 * Scheduling helpers from batch_metrics — metrics chip gate + summary.
 * Gantt / ParallelTimeline page UI removed with collaboration-graph timeline layout.
 */
import { describe, expect, it } from "vitest";
import {
  fmtMs,
  hasParallelTimeline,
  parallelTimelineMetricsSummary,
} from "../ParallelTimeline";

function metrics(
  overrides: Partial<BatchMetricsSnapshot> &
    Pick<BatchMetricsSnapshot, "timeline">,
): BatchMetricsSnapshot {
  return {
    nodes: 2,
    width: 2,
    peakRunning: 2,
    wallMs: 1000,
    busyMs: 800,
    slotStarved: 0,
    completed: 2,
    failed: 0,
    skipped: 0,
    bindBoundaries: 0,
    scopeBoundaries: 0,
    checkpointBoundaries: 0,
    escalations: 0,
    scopeEscalations: 0,
    ...overrides,
  };
}

function exec(batches: BatchMetricsSnapshot[]): Execution {
  return {
    id: "e1",
    planType: "multi_agent",
    status: "completed",
    taskSummary: "t",
    agents: [],
    runs: [],
    batches,
    frames: [],
    frameCursor: 0,
  } as unknown as Execution;
}

describe("hasParallelTimeline (metrics gate)", () => {
  it("true when ≥2 timeline entries across batches", () => {
    expect(
      hasParallelTimeline(
        exec([
          metrics({
            timeline: [
              { runId: "a", startMs: 0, endMs: 100, outcome: "ok" },
              { runId: "b", startMs: 0, endMs: 80, outcome: "ok" },
            ],
          }),
        ]),
      ),
    ).toBe(true);
  });

  it("true when entries span multiple batches", () => {
    expect(
      hasParallelTimeline(
        exec([
          metrics({
            timeline: [{ runId: "a", startMs: 0, endMs: 100, outcome: "ok" }],
          }),
          metrics({
            timeline: [{ runId: "b", startMs: 0, endMs: 50, outcome: "ok" }],
          }),
        ]),
      ),
    ).toBe(true);
  });

  it("false for a single bar", () => {
    expect(
      hasParallelTimeline(
        exec([
          metrics({
            timeline: [{ runId: "a", startMs: 0, endMs: 100, outcome: "ok" }],
          }),
        ]),
      ),
    ).toBe(false);
  });

  it("false with empty batches", () => {
    expect(hasParallelTimeline(exec([]))).toBe(false);
  });
});

describe("parallelTimelineMetricsSummary", () => {
  it("summarizes peak · wall · optional starvation", () => {
    expect(
      parallelTimelineMetricsSummary(
        exec([
          metrics({
            peakRunning: 3,
            wallMs: 2500,
            slotStarved: 2,
            timeline: [
              { runId: "a", startMs: 0, endMs: 100, outcome: "ok" },
              { runId: "b", startMs: 0, endMs: 80, outcome: "ok" },
            ],
          }),
        ]),
      ),
    ).toBe("峰值 3 · 串行 2 · 2.5s");
  });

  it("null when no timeline rows", () => {
    expect(
      parallelTimelineMetricsSummary(exec([metrics({ timeline: [] })])),
    ).toBeNull();
  });
});

describe("fmtMs", () => {
  it("keeps sub-second in ms", () => {
    expect(fmtMs(420)).toBe("420ms");
  });

  it("formats seconds with one decimal", () => {
    expect(fmtMs(1500)).toBe("1.5s");
  });
});
