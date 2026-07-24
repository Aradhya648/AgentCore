import { beforeEach, describe, expect, it } from "vitest";
import {
  type ExecutionPlan,
  type RunFrame,
  execRuntime,
  hasUnsettledRuns,
  useExecutionStore,
} from "../../execution";

// hasUnsettledRuns drives the message_end「后台托管继续跑」hold: true = still has a
// pending/running run (keep the graph running), false = every run terminal OR no
// runs to wait on (let message_end 收口). NOT the exact negation of the private
// runsAllSettled reconcile check — both are false on a 0-run graph.

const MID = "m";
const store = () => useExecutionStore.getState();
const rt = () => execRuntime(store(), MID);

const onePlan: ExecutionPlan = {
  id: "e1",
  planType: "multi_agent",
  taskSummary: "t",
  agents: [{ id: "a1", role: "r" }],
  runs: [{ id: "r1", agentId: "a1", task: "t", dependsOn: [] }],
};

function started(runId = "r1", agentId = "a1"): RunFrame {
  return {
    t: 1,
    kind: "run_started",
    agentId,
    runId,
    parentRunId: null,
    runKind: "agent",
    continuesRunId: null,
  };
}

function completed(runId = "r1", agentId = "a1"): RunFrame {
  return {
    t: 2,
    kind: "run_completed",
    runId,
    agentId,
    outputSummary: "ok",
    durationMs: 1,
  };
}

beforeEach(() => {
  useExecutionStore.setState({ byId: {} });
});

describe("hasUnsettledRuns", () => {
  it("is false when the slot has no plan", () => {
    expect(hasUnsettledRuns(rt())).toBe(false);
  });

  it("is true while a plan-declared run is still pending", () => {
    store().startExecution(onePlan, MID);
    expect(hasUnsettledRuns(rt())).toBe(true);
  });

  it("is true while a run is running", () => {
    store().startExecution(onePlan, MID);
    store().recordFrame(started(), MID);
    expect(hasUnsettledRuns(rt())).toBe(true);
  });

  it("is false once every run reached a terminal state", () => {
    store().startExecution(onePlan, MID);
    store().recordFrame(started(), MID);
    store().recordFrame(completed(), MID);
    expect(hasUnsettledRuns(rt())).toBe(false);
  });

  it("is false for a plan that declares no runs (nothing in flight to wait on)", () => {
    store().startExecution({ ...onePlan, runs: [] }, MID);
    expect(hasUnsettledRuns(rt())).toBe(false);
  });
});
