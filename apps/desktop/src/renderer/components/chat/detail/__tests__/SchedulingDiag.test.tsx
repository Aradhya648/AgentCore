// @vitest-environment jsdom
/**
 * Render test for the 调度埋点量化 diagnostic block (深层诊断指标, 前端UX设计.md §十).
 *
 * The panel is gated behind 诊断模式 and lives in the run-detail side panel, so the
 * #/preview shoot harness never reaches it — this asserts the DOM directly: the avg
 * concurrency (busyMs/wallMs), the conditional rows (slot-starved / 自我纠偏 boundaries /
 * 队员上报 only when > 0), and the multi-batch 批次 numbering.
 */

import type { BatchMetricsSnapshot } from "@/stores/execution";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CollabDiag, SchedulingDiag } from "../sections/RunDiagnostics";

afterEach(cleanup);

const base: BatchMetricsSnapshot = {
  nodes: 3,
  width: 4,
  peakRunning: 2,
  wallMs: 1000,
  busyMs: 1500,
  slotStarved: 0,
  completed: 3,
  failed: 0,
  skipped: 0,
  bindBoundaries: 0,
  scopeBoundaries: 0,
  checkpointBoundaries: 0,
  escalations: 0,
  scopeEscalations: 0,
  timeline: [],
};

describe("SchedulingDiag (调度诊断块)", () => {
  it("shows core counts + computes avg concurrency (busyMs/wallMs)", () => {
    render(<SchedulingDiag batches={[base]} />);
    expect(screen.getByText("3 · 上限 4 · 峰值 2")).toBeTruthy();
    // 1500 / 1000 = 1.50 平均并发, wall 1000ms.
    expect(screen.getByText("1.50 · 1000ms")).toBeTruthy();
    expect(screen.getByText("完成 3")).toBeTruthy();
  });

  it("hides slot-starved / boundary / escalation rows when zero", () => {
    render(<SchedulingDiag batches={[base]} />);
    expect(screen.queryByText("槽位等待")).toBeNull();
    expect(screen.queryByText("自我纠偏")).toBeNull();
    expect(screen.queryByText("队员上报")).toBeNull();
  });

  it("surfaces failures/skips, slot starvation, boundaries and escalations when present", () => {
    render(
      <SchedulingDiag
        batches={[
          {
            ...base,
            failed: 1,
            skipped: 2,
            slotStarved: 5,
            bindBoundaries: 1,
            scopeBoundaries: 2,
            checkpointBoundaries: 0,
            escalations: 3,
            scopeEscalations: 1,
          },
        ]}
      />,
    );
    expect(screen.getByText("完成 3 · 失败 1 · 跳过 2")).toBeTruthy();
    expect(screen.getByText("5 次")).toBeTruthy();
    expect(screen.getByText("绑定 1 · 操舵 2 · 复核 0")).toBeTruthy();
    expect(screen.getByText("3（scope 1）")).toBeTruthy();
  });

  it("guards divide-by-zero wall time with —", () => {
    render(<SchedulingDiag batches={[{ ...base, wallMs: 0, busyMs: 0 }]} />);
    expect(screen.getByText("— · 0ms")).toBeTruthy();
  });

  it("numbers each segment when a turn has multiple batches", () => {
    render(
      <SchedulingDiag
        batches={[base, { ...base, nodes: 1, peakRunning: 1 }]}
      />,
    );
    expect(screen.getByText("调度 · 2 批")).toBeTruthy();
    expect(screen.getByText("批次 1")).toBeTruthy();
    expect(screen.getByText("批次 2")).toBeTruthy();
  });
});

describe("CollabDiag (协作质量诊断块)", () => {
  it("renders non-zero orchestration signals", () => {
    render(
      <CollabDiag
        collab={{
          boundary_yields: 1,
          scope_signals: 2,
          revises: 1,
          escalations: 3,
        }}
      />,
    );
    expect(screen.getByText("协作质量")).toBeTruthy();
    expect(screen.getByText("自我纠偏让出")).toBeTruthy();
    expect(screen.getByText("漂移信号")).toBeTruthy();
    expect(screen.getByText("定向唤回")).toBeTruthy();
    expect(screen.getByText("队员上报")).toBeTruthy();
  });

  it("renders nothing when all signals are zero", () => {
    const { container } = render(
      <CollabDiag
        collab={{
          boundary_yields: 0,
          scope_signals: 0,
          revises: 0,
          escalations: 0,
        }}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("surfaces audit_drops when non-zero", () => {
    render(
      <CollabDiag
        collab={{
          boundary_yields: 0,
          scope_signals: 0,
          revises: 0,
          escalations: 0,
          audit_drops: 2,
        }}
      />,
    );
    expect(screen.getByText("协作质量")).toBeTruthy();
    expect(screen.getByText("审计采集降级")).toBeTruthy();
    expect(screen.getByText("2 次")).toBeTruthy();
  });
});
