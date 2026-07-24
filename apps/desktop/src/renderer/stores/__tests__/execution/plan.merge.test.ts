import { describe, expect, it } from "vitest";
import { type ExecutionPlan, mergePlanInto } from "../../execution";

function basePlan(summary: string, runId: string): ExecutionPlan {
  return {
    id: "exec-1",
    planType: "multi_agent",
    taskSummary: summary,
    agents: [{ id: "a1", role: "研究员" }],
    runs: [
      {
        id: runId,
        agentId: "a1",
        task: "调研",
        dependsOn: [],
        actId: "act-1",
      },
    ],
    acts: [
      {
        actId: "act-1",
        kind: "multi_agent",
        title: summary,
        anchorRunId: null,
        authorizedBy: null,
      },
    ],
  };
}

describe("mergePlanInto taskSummary", () => {
  it("keeps host/first-act taskSummary when a later debate act merges in", () => {
    const host = basePlan("团队调研任务", "run-host");
    const debate: ExecutionPlan = {
      id: "exec-1",
      planType: "debate",
      taskSummary: "该不该上微服务",
      agents: [{ id: "mod", role: "主持人" }],
      runs: [
        {
          id: "run-mod",
          agentId: "mod",
          task: "主持",
          dependsOn: [],
          actId: "act-2",
        },
      ],
      acts: [
        {
          actId: "act-2",
          kind: "debate",
          title: "该不该上微服务",
          anchorRunId: null,
          authorizedBy: "stage_card",
        },
      ],
    };
    const merged = mergePlanInto(host, debate);
    expect(merged.taskSummary).toBe("团队调研任务");
    expect(merged.runs.map((r) => r.id).sort()).toEqual([
      "run-host",
      "run-mod",
    ]);
  });

  it("falls back to next summary only when host summary is empty", () => {
    const host = basePlan("", "run-host");
    const next = basePlan("后幕命题", "run-2");
    expect(mergePlanInto(host, next).taskSummary).toBe("后幕命题");
  });
});
