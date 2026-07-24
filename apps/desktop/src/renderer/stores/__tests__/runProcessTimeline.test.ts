import { type ExecutionPlan, projectExecution } from "@/stores/execution";
import type { RunFrame } from "@/stores/execution";
import { describe, expect, it } from "vitest";

const plan: ExecutionPlan = {
  id: "exec1",
  planType: "multi_agent",
  taskSummary: "调研",
  agents: [
    {
      id: "w1",
      role: "调研员",
      thinking: true,
    },
  ],
  runs: [
    {
      id: "r1",
      agentId: "w1",
      task: "调研竞品",
      dependsOn: [],
    },
  ],
};

describe("worker run process timeline fold", () => {
  it("interleaves reasoning → tool → content on RunNode.process", () => {
    const frames: RunFrame[] = [
      {
        t: 1,
        kind: "run_started",
        runId: "r1",
        agentId: "w1",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      {
        t: 2,
        kind: "run_reasoning_delta",
        runId: "r1",
        agentId: "w1",
        delta: "先搜。",
      },
      {
        t: 3,
        kind: "tool_use_start",
        toolCallId: "tc1",
        toolName: "web_search",
        arguments: { query: "x" },
        runId: "r1",
      },
      {
        t: 4,
        kind: "tool_use_end",
        toolCallId: "tc1",
        result: "ok",
        display: null,
        status: "success",
      },
      {
        t: 5,
        kind: "run_output_delta",
        runId: "r1",
        agentId: "w1",
        delta: "结论。",
      },
    ];
    const exec = projectExecution(plan, frames, "running");
    const run = exec.runs.find((r) => r.id === "r1");
    expect(run?.process.map((s) => s.kind)).toEqual([
      "reasoning",
      "tool",
      "content",
    ]);
    expect(run?.process[0]).toMatchObject({
      kind: "reasoning",
      text: "先搜。",
    });
    expect(run?.process[1]).toMatchObject({
      kind: "tool",
      id: "tc1",
      status: "success",
      result: "ok",
    });
    expect(run?.process[2]).toMatchObject({
      kind: "content",
      text: "结论。",
    });
  });
});
