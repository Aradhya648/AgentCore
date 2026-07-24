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

const MID = "msg-synth-preview";

const plan: ExecutionPlan = {
  id: "exec-1",
  planType: "multi_agent",
  taskSummary: "并行调研",
  agents: [
    { id: "w1", role: "研究员" },
    { id: "w2", role: "撰写员" },
  ],
  runs: [
    { id: "r1", agentId: "w1", task: "调研", dependsOn: [] },
    { id: "r2", agentId: "w2", task: "撰写", dependsOn: [] },
  ],
};

const bothWorkersDone: RunFrame[] = [
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
    kind: "run_started",
    runId: "r2",
    agentId: "w2",
    parentRunId: null,
    runKind: "agent",
    continuesRunId: null,
  },
  {
    t: 3,
    kind: "run_completed",
    runId: "r1",
    agentId: "w1",
    outputSummary: "调研完成",
    durationMs: 100,
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

describe("StatusStrip · team_synthesis_preview draft", () => {
  it("renders CEO synthesis draft body from preview.text", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    useExecutionStore.getState().setTeamSynthesisPreview(
      {
        execution_id: "exec-1",
        completed: 1,
        total: 2,
        headline: "合成草稿更新 · 已完成 1/2",
        text: "两边方向一致：优先方案 A，撰写员按此定稿。",
        workers: [],
        in_progress: true,
      },
      MID,
    );

    renderStrip(projectExecution(plan, [], "running"));

    expect(screen.getByTestId("team-synthesis-preview")).toBeTruthy();
    expect(screen.getByText("进展中")).toBeTruthy();
    expect(screen.getByText("合成草稿更新 · 已完成 1/2")).toBeTruthy();
    expect(screen.getByTestId("team-synthesis-draft").textContent).toContain(
      "两边方向一致：优先方案 A",
    );
  });

  it("里程碑草稿：系统进度（run 摘要）为主、CEO 小结为辅", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    // CEO 里程碑 update_synthesis：workers=[]、text=自由文草稿。
    useExecutionStore.getState().setTeamSynthesisPreview(
      {
        execution_id: "exec-1",
        completed: 1,
        total: 2,
        headline: "合成草稿更新 · 已完成 1/2",
        text: "方向已对齐：研究支持方案 A，进入撰写。",
        workers: [],
        in_progress: true,
      },
      MID,
    );
    // 系统进度权威来源：r1 已完成（有 outputSummary），r2 仍在跑 → 非合成空窗。
    const oneDone: RunFrame[] = [
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
        kind: "run_started",
        runId: "r2",
        agentId: "w2",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      {
        t: 3,
        kind: "run_completed",
        runId: "r1",
        agentId: "w1",
        outputSummary: "调研完成",
        durationMs: 100,
      },
    ];

    renderStrip(projectExecution(plan, oneDone, "running"));

    // 系统自动进度为主：确定性 run 摘要出现（非 CEO 逐条手写）。
    expect(screen.getByText(/研究员：调研完成/)).toBeTruthy();
    // CEO 里程碑总结为辅：带「CEO 小结」标签的辅助块。
    expect(screen.getByTestId("team-synthesis-ceo-note")).toBeTruthy();
    expect(screen.getByText("CEO 小结")).toBeTruthy();
    expect(screen.getByTestId("team-synthesis-draft").textContent).toContain(
      "方向已对齐",
    );
  });

  it("renders worker blurbs when present (no separate draft block)", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    useExecutionStore.getState().setTeamSynthesisPreview(
      {
        execution_id: "exec-1",
        completed: 1,
        total: 2,
        headline: "已完成 1/2：✅ 研究员 ⏳ 撰写员",
        text: "已完成 1/2：✅ 研究员 ⏳ 撰写员\n· 研究员：调研结论",
        workers: [
          {
            run_id: "r1",
            role: "研究员",
            status: "completed",
            summary: "调研结论",
          },
          {
            run_id: "r2",
            role: "撰写员",
            status: "pending",
            summary: "",
          },
        ],
        in_progress: true,
      },
      MID,
    );

    renderStrip(projectExecution(plan, [], "running"));

    expect(screen.getByText(/研究员：调研结论/)).toBeTruthy();
    expect(screen.queryByTestId("team-synthesis-draft")).toBeNull();
  });

  it("汇总空窗：工人全完成仍 running 时显示确定性进度 + 活性指示", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    // 空窗期常见：最后一条 preview 仍停在 1/2，无新事件。
    useExecutionStore.getState().setTeamSynthesisPreview(
      {
        execution_id: "exec-1",
        completed: 1,
        total: 2,
        headline: "已完成 1/2：✅ 研究员 ⏳ 撰写员",
        text: "已完成 1/2：✅ 研究员 ⏳ 撰写员\n· 研究员：调研结论",
        workers: [
          {
            run_id: "r1",
            role: "研究员",
            status: "completed",
            summary: "调研结论",
          },
          {
            run_id: "r2",
            role: "撰写员",
            status: "pending",
            summary: "",
          },
        ],
        in_progress: true,
      },
      MID,
    );

    const execution = projectExecution(plan, bothWorkersDone, "running");
    expect(execution.progress).toEqual({ completed: 2, total: 2 });

    renderStrip(execution);

    expect(screen.getByTestId("status-strip-synthesizing")).toBeTruthy();
    expect(screen.getByTestId("status-strip-running-title").textContent).toBe(
      "2/2 已完成，正在生成汇总",
    );
    expect(
      screen.getByTestId("team-synthesis-preview").dataset.synthesizing,
    ).toBe("true");
    expect(screen.getByText("生成汇总")).toBeTruthy();
    expect(screen.getByTestId("team-synthesis-headline").textContent).toBe(
      "2/2 已完成，正在生成汇总",
    );
    expect(screen.getByTestId("team-synthesis-pulse")).toBeTruthy();
    // 空窗用 execution 完成态补全 blurbs（不依赖过期 preview 的 1/2 workers）。
    expect(screen.getByText(/研究员：调研完成/)).toBeTruthy();
    expect(screen.getByText(/撰写员：撰写完成/)).toBeTruthy();
  });

  it("汇总空窗：无 preview 事件时仍显示确定性进度（不注入 CEO 气泡）", () => {
    useExecutionStore.getState().startExecution(plan, MID);
    const execution = projectExecution(plan, bothWorkersDone, "running");

    renderStrip(execution);

    expect(screen.getByTestId("status-strip-synthesizing")).toBeTruthy();
    expect(screen.getByTestId("status-strip-running-title").textContent).toBe(
      "2/2 已完成，正在生成汇总",
    );
    expect(
      screen.getByTestId("team-synthesis-preview").dataset.synthesizing,
    ).toBe("true");
    expect(screen.queryByTestId("team-synthesis-draft")).toBeNull();
  });
});
