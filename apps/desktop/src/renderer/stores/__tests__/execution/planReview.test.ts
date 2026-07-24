import type { SSEEvent } from "@/types/events";
import { describe, expect, it } from "vitest";
import {
  type RunFrame,
  frameFromEvent,
  projectExecution,
} from "../../execution";
import { plan, started } from "./fixtures";

// 结构化挂起 2a (7.2A): a `checkpoint_after` pause folds into the graph as
// plan_review frames so the gated step shows a「待放行 / 已放行 / 已停止」badge —
// driven by run.checkpoint, the same fold the timeline + reload replay run.
describe("plan_review checkpoint badge (结构化挂起 2a)", () => {
  const completed = (runId: string, agentId: string, t: number): RunFrame => ({
    t,
    kind: "run_completed",
    runId,
    agentId,
    outputSummary: "产出",
    durationMs: 1,
  });
  const required = (checkpointId: string, runIds: string[]): RunFrame => ({
    t: 5,
    kind: "plan_review_required",
    checkpointId,
    runIds,
  });
  const resolved = (
    checkpointId: string,
    decision: "continue" | "stop",
  ): RunFrame => ({
    t: 6,
    kind: "plan_review_resolved",
    checkpointId,
    decision,
  });

  it("marks the gated step pending on plan_review_required", () => {
    const frames: RunFrame[] = [
      started("agent-1", "run-1"),
      completed("run-1", "agent-1", 2),
      required("c1", ["run-1"]),
    ];
    const exec = projectExecution(plan, frames, "running");
    expect(exec.runs.find((r) => r.id === "run-1")?.checkpoint).toEqual({
      status: "pending",
      decision: null,
    });
    // A node that was not gated carries no checkpoint badge.
    expect(exec.runs.find((r) => r.id === "run-2")?.checkpoint).toBeNull();
  });

  it("resolves the gated step to continue (已放行)", () => {
    const frames: RunFrame[] = [
      completed("run-1", "agent-1", 2),
      required("c1", ["run-1"]),
      resolved("c1", "continue"),
    ];
    const run = projectExecution(plan, frames, "running").runs.find(
      (r) => r.id === "run-1",
    );
    expect(run?.checkpoint).toEqual({
      status: "resolved",
      decision: "continue",
    });
  });

  it("resolves the gated step to stop (已停止)", () => {
    const frames: RunFrame[] = [
      completed("run-1", "agent-1", 2),
      required("c1", ["run-1"]),
      resolved("c1", "stop"),
    ];
    const run = projectExecution(plan, frames, "cancelled").runs.find(
      (r) => r.id === "run-1",
    );
    expect(run?.checkpoint).toEqual({ status: "resolved", decision: "stop" });
  });

  it("leaves every node's checkpoint null without plan_review frames", () => {
    const exec = projectExecution(
      plan,
      [started("agent-1", "run-1")],
      "running",
    );
    expect(exec.runs.every((r) => r.checkpoint === null)).toBe(true);
  });

  it("frameFromEvent maps plan_review events (runIds come from steps)", () => {
    const req = frameFromEvent({
      type: "plan_review_required",
      timestamp: "",
      payload: {
        checkpoint_id: "c1",
        conversation_id: "a",
        steps: [{ run_id: "run-1", role: "R", summary: "s" }],
        pending: [],
      },
    } as SSEEvent);
    expect(req).toMatchObject({
      kind: "plan_review_required",
      checkpointId: "c1",
      runIds: ["run-1"],
    });
    const res = frameFromEvent({
      type: "plan_review_resolved",
      timestamp: "",
      payload: { checkpoint_id: "c1", decision: "stop", note: "" },
    } as SSEEvent);
    expect(res).toMatchObject({
      kind: "plan_review_resolved",
      checkpointId: "c1",
      decision: "stop",
    });
  });
});
