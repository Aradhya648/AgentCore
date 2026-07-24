import type { ExecutionPlan, RunFrame } from "../../execution";
import { execRuntime, useExecutionStore } from "../../execution";

export const plan: ExecutionPlan = {
  id: "exec-1",
  planType: "multi_agent",
  taskSummary: "分析对比 React 和 Vue",
  agents: [
    { id: "agent-1", role: "React 研究员" },
    { id: "agent-2", role: "Vue 研究员" },
  ],
  runs: [
    { id: "run-1", agentId: "agent-1", task: "研究 React", dependsOn: [] },
    { id: "run-2", agentId: "agent-2", task: "研究 Vue", dependsOn: [] },
    {
      id: "run-3",
      agentId: "agent-1",
      task: "汇总对比",
      dependsOn: ["run-1", "run-2"],
    },
  ],
};

export const store = () => useExecutionStore.getState();
// Every turn's execution is keyed by its assistant message id (§9.3). This suite
// drives a single message slot, so mutators take MID and reads project it.
export const MID = "msg-1";
export const rt = () => execRuntime(store(), MID);

/** run_started frame with the 阶段2 declaration slots defaulted (阶段1 flat). */
export function started(agentId: string, runId: string, t = 1): RunFrame {
  return {
    t,
    kind: "run_started",
    agentId,
    runId,
    parentRunId: null,
    runKind: "agent",
    continuesRunId: null,
  };
}

/** 同人接续 run_started：未入 plan，continuesRunId 指现场根（星型）。 */
export function continued(
  runId: string,
  continuesRunId: string,
  t = 1,
  round?: number,
  parentRunId: string | null = null,
): Extract<RunFrame, { kind: "run_started" }> {
  return {
    t,
    kind: "run_started",
    agentId: runId,
    runId,
    parentRunId,
    runKind: "agent",
    continuesRunId,
    ...(round != null ? { round } : {}),
  };
}

/** @deprecated test alias — parent arg is the continues root. */
export function revised(
  runId: string,
  continuesRunId: string,
  _revision: number,
  t = 1,
  round?: number,
): Extract<RunFrame, { kind: "run_started" }> {
  return continued(runId, continuesRunId, t, round);
}

export function resetExecutionStore(): void {
  useExecutionStore.setState({ byId: {} });
}
