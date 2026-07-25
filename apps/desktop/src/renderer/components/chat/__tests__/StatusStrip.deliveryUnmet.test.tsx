// @vitest-environment jsdom
import { TooltipProvider } from "@/components/ui/tooltip";
import { conversationKeys } from "@/lib/queryKeys";
import {
  type ExecutionPlan,
  ExecutionScopeContext,
  type RunFrame,
  projectExecution,
  useExecutionStore,
} from "@/stores/execution";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StatusStrip } from "../StatusStrip";

const MID = "msg-delivery-unmet-strip";

const plan: ExecutionPlan = {
  id: "exec-delivery",
  planType: "multi_agent",
  taskSummary: "交付对账",
  agents: [
    { id: "w1", role: "研究员" },
    { id: "w2", role: "撰写员" },
  ],
  runs: [
    { id: "r1", agentId: "w1", task: "调研", dependsOn: [] },
    { id: "r2", agentId: "w2", task: "撰写", dependsOn: [] },
  ],
};

const doneFrames: RunFrame[] = [
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
    kind: "run_completed",
    runId: "r1",
    agentId: "w1",
    outputSummary: "调研完成",
    durationMs: 100,
  },
  {
    t: 3,
    kind: "run_started",
    runId: "r2",
    agentId: "w2",
    parentRunId: null,
    runKind: "agent",
    continuesRunId: null,
  },
  {
    t: 4,
    kind: "run_completed",
    runId: "r2",
    agentId: "w2",
    outputSummary: "撰写完成",
    durationMs: 120,
  },
];

function renderStrip(execution: ReturnType<typeof projectExecution>) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
    },
  });
  client.setQueryData(conversationKeys.grouped, {
    folders: [],
    conversations: [],
  });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ExecutionScopeContext.Provider value={MID}>
          <StatusStrip
            execution={execution}
            expanded
            onToggle={() => {}}
            onMaximize={() => {}}
            onReplay={() => {}}
          />
        </ExecutionScopeContext.Provider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  useExecutionStore.setState({ byId: {} });
});

describe("StatusStrip · delivery unmet 词轴", () => {
  it("无 delivery_status 时保持「团队完成」", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    const exec = projectExecution(plan, doneFrames, "completed");
    renderStrip(exec);
    expect(screen.getByText("团队完成")).toBeTruthy();
    expect(screen.queryByText("已跑完 · 交付未过关")).toBeNull();
  });

  it("partial / blocked 时改为「已跑完 · 交付未过关」", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    useExecutionStore.getState().setDeliveryStatus(
      {
        execution_id: "exec-delivery",
        state: "partial",
        summary: "已交付 1 个文件；1 项缺口",
        delivered_files: ["a.md"],
        gaps: [{ role: "验收", description: "缺验证" }],
        actions: [],
      },
      MID,
    );
    const exec = projectExecution(plan, doneFrames, "completed");
    renderStrip(exec);
    expect(screen.getByText("已跑完 · 交付未过关")).toBeTruthy();
    expect(screen.queryByText("团队完成")).toBeNull();
  });

  it("delivered 对账不改「团队完成」（卡本身也不出）", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    useExecutionStore.getState().setDeliveryStatus(
      {
        execution_id: "exec-delivery",
        state: "delivered",
        summary: "已交付 2 个文件",
        delivered_files: ["a.md", "b.md"],
        gaps: [],
        actions: [],
      },
      MID,
    );
    const exec = projectExecution(plan, doneFrames, "completed");
    renderStrip(exec);
    expect(screen.getByText("团队完成")).toBeTruthy();
    expect(screen.queryByText("已跑完 · 交付未过关")).toBeNull();
  });
});
