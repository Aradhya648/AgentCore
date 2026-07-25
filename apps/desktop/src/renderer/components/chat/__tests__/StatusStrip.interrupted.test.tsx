// @vitest-environment jsdom
/**
 * User stop seals cancelled — StatusStrip paints stopped chrome + 重试,
 * never frameless「继续」/ live spinner.
 */
import { TooltipProvider } from "@/components/ui/tooltip";
import { conversationKeys } from "@/lib/queryKeys";
import {
  type ExecutionPlan,
  ExecutionScopeContext,
  type RunFrame,
  projectExecution,
} from "@/stores/execution";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusStrip } from "../StatusStrip";

const MID = "msg-stopped-strip";

vi.mock("@/stores/conversation", async () => {
  const actual = await vi.importActual<typeof import("@/stores/conversation")>(
    "@/stores/conversation",
  );
  return {
    ...actual,
    useActiveGenerating: () => false,
    useActiveTurnPhase: () => "idle",
    useConversationStore: (
      sel: (s: {
        currentConversationId: string;
        stopGeneration: () => void;
      }) => unknown,
    ) =>
      sel({
        currentConversationId: "conv-1",
        stopGeneration: () => {},
      }),
    getActiveRuntime: () => ({ messages: [] }),
  };
});

vi.mock("@/services/turns", () => ({
  lastUserMessageId: () => null,
  runRetryFailed: vi.fn(),
  runRegenerate: vi.fn(),
}));

const plan: ExecutionPlan = {
  id: "exec-stopped",
  planType: "multi_agent",
  taskSummary: "并行调研",
  agents: [{ id: "w1", role: "研究员" }],
  runs: [{ id: "r1", agentId: "w1", task: "调研", dependsOn: [] }],
};

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
    kind: "run_completed",
    runId: "r1",
    agentId: "w1",
    outputSummary: "完成调研",
    durationMs: 1000,
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

describe("StatusStrip · user stop cancelled", () => {
  it("status=cancelled → 已停止 + 重试, no 继续 / spinner / stop", () => {
    const exec = projectExecution(plan, frames, "cancelled");
    expect(exec.status).toBe("cancelled");

    const { container } = renderStrip(exec);

    expect(screen.getByText("已停止")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "继续" })).toBeNull();
    expect(container.querySelector(".animate-spin")).toBeNull();
    expect(screen.queryByLabelText("停止任务")).toBeNull();
  });
});
