// @vitest-environment jsdom
/**
 * 交付验收区块：标题词轴 + 「团队可能重派」非 unmet 恒显（对齐桌面 DeliveryStatusCard）。
 */
import { TeamView } from "@/components/TeamView";
import type {
  ProjectedAgent,
  ProjectedRun,
} from "@agentcore/protocol-conformance";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

function makeAgent(
  p: Partial<ProjectedAgent> & { id: string; role: string },
): ProjectedAgent {
  return {
    thinking: false,
    status: "completed",
    currentRunId: null,
    output: "",
    reasoning: "",
    toolProgress: null,
    ...p,
  };
}

function makeRun(p: Partial<ProjectedRun> & { id: string }): ProjectedRun {
  return {
    agentId: "a1",
    task: "task",
    status: "completed",
    dependsOn: [],
    outputSummary: null,
    debrief: null,
    durationMs: null,
    error: null,
    parentRunId: null,
    kind: "agent",
    role: "队员",
    model: null,
    usage: null,
    cost: null,
    stance: null,
    group: null,
    round: 0,
    continuesRunId: null,
    revised: null,
    replacesRunId: null,
    checkpoint: null,
    receivedContext: [],
    escalations: [],
    process: [],
    actId: "act-1",
    ...p,
  };
}

const agents = [makeAgent({ id: "a1", role: "队员" })];
const runs = [makeRun({ id: "r1", agentId: "a1" })];

describe("TeamView · 交付验收", () => {
  it("标题为「交付验收」；有续派 CTA 时显「团队可能重派」", () => {
    render(
      <TeamView
        agents={agents}
        runs={runs}
        progress={{ completed: 1, total: 1 }}
        status="completed"
        acts={[]}
        teamNotes={[]}
        evidenceLedger={[]}
        deliveryStatus={{
          execution_id: "e1",
          state: "partial",
          summary: "已交付 1 个文件；1 项未完成",
          delivered_files: ["a.md"],
          gaps: [{ role: "写作", description: "成篇未写完" }],
          actions: [
            {
              kind: "continue_skipped_runs",
              description: "点此续跑未执行节点",
              prompt: "请续跑",
            },
          ],
          artifacts: [
            { path: "a.md", status: "accepted" },
            {
              path: "b.md",
              status: "rejected",
              reason: "citations_unverified",
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("交付验收")).toBeTruthy();
    expect(screen.getByText("团队可能重派")).toBeTruthy();
    expect(screen.queryByText("完成条件")).toBeNull();
    expect(
      screen.getByText("已交付 1 个；未通过 1 个（详见下方产物清单）"),
    ).toBeTruthy();
  });

  it("无续派 CTA 时隐藏「团队可能重派」", () => {
    render(
      <TeamView
        agents={agents}
        runs={runs}
        progress={{ completed: 1, total: 1 }}
        status="completed"
        acts={[]}
        teamNotes={[]}
        evidenceLedger={[]}
        deliveryStatus={{
          execution_id: "e2",
          state: "blocked",
          summary: "未能交付：1 项缺口",
          delivered_files: [],
          gaps: [{ role: "验收", description: "尚无 code_execute" }],
          actions: [],
        }}
      />,
    );
    expect(screen.getByText("交付验收")).toBeTruthy();
    expect(screen.queryByText("团队可能重派")).toBeNull();
  });
});
