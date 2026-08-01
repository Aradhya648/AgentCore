import { ensureStreamingAssistant } from "@/services/sse/contentBuffer";
import { dispatchSSEEvent } from "@/services/sse/dispatch";
import { stopConversation } from "@/services/stopTurn";
import {
  beginTurnPreflight,
  enterTurnStreaming,
  getRuntime,
  getTurnPhase,
  throwIfCannotOpenStream,
  useConversationStore,
} from "@/stores/conversation";
import {
  type ExecutionPlan,
  execRuntime,
  useExecutionStore,
} from "@/stores/execution";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  api: {
    post: vi.fn(),
  },
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifyInfo: vi.fn(),
  notifyWarning: vi.fn(),
  notifySuccess: vi.fn(),
}));

import { api } from "@/services/api";

const CID = "conv-turn-phase";
const apiPost = vi.mocked(api.post);

const plan: ExecutionPlan = {
  id: "exec-stop",
  planType: "multi_agent",
  taskSummary: "并行调研",
  agents: [
    { id: "w1", role: "研究员" },
    { id: "w2", role: "撰写员" },
  ],
  runs: [
    { id: "r1", agentId: "w1", task: "调研", dependsOn: [] },
    { id: "r2", agentId: "w2", task: "撰写", dependsOn: ["r1"] },
  ],
};

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: CID, byId: {} });
  useConversationStore.getState().switchConversation(CID);
  useExecutionStore.setState({ byId: {} });
  apiPost.mockReset();
  apiPost.mockResolvedValue({ stopped: true });
});

describe("turn stop lifecycle", () => {
  it("预检期间停止 → throwIfCannotOpenStream 阻断开流", () => {
    beginTurnPreflight(CID);
    expect(getTurnPhase(CID)).toBe("preflight");

    useConversationStore.getState().stopGeneration();
    expect(getTurnPhase(CID)).toBe("stopping");
    // 诚实过渡：不本地 finalize，isGenerating 保持至后端终态
    expect(getRuntime(CID).isGenerating).toBe(false);

    expect(() => throwIfCannotOpenStream(CID)).toThrow(
      expect.objectContaining({ name: "AbortError" }),
    );
  });

  it("已 abort 的 signal → throwIfCannotOpenStream 阻断", () => {
    beginTurnPreflight(CID);
    const ac = new AbortController();
    ac.abort();
    expect(() => throwIfCannotOpenStream(CID, ac.signal)).toThrow(
      expect.objectContaining({ name: "AbortError" }),
    );
  });

  it("停止后迟到 content_delta / tool 事件被丢弃，不重建气泡、不拉回 isGenerating", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    useConversationStore.getState().createAssistantMessage(CID);
    const beforeCount = getRuntime(CID).messages.length;

    useConversationStore.getState().stopGeneration();
    expect(getTurnPhase(CID)).toBe("stopping");
    expect(getRuntime(CID).isGenerating).toBe(true);

    dispatchSSEEvent(
      {
        type: "content_delta",
        payload: { delta: "迟到正文" },
      } as never,
      { conversationId: CID, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "tool_use_start",
        payload: {
          tool_use_id: "t1",
          tool_name: "web_search",
          input: {},
        },
      } as never,
      { conversationId: CID, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "message_start",
        payload: { message_id: "m-late", trace_id: null },
      } as never,
      { conversationId: CID, source: "server" },
    );

    ensureStreamingAssistant(CID);

    expect(getRuntime(CID).isGenerating).toBe(true);
    expect(getRuntime(CID).messages.length).toBe(beforeCount);
    const last = getRuntime(CID).messages.at(-1);
    expect(last?.content ?? "").not.toContain("迟到正文");
    expect(last?.isStreaming).toBe(true);
  });

  it("stopping 态继续消费 run_* 帧，不伪造 cancelled", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    const mid = useConversationStore.getState().createAssistantMessage(CID);
    if (!mid) throw new Error("expected assistant message id");
    useExecutionStore.getState().startExecution(plan, mid);
    useExecutionStore.getState().recordFrame(
      {
        t: 1,
        kind: "run_started",
        runId: "r1",
        agentId: "w1",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      mid,
    );

    useConversationStore.getState().stopGeneration();
    expect(getTurnPhase(CID)).toBe("stopping");
    expect(execRuntime(useExecutionStore.getState(), mid).status).toBe(
      "running",
    );

    dispatchSSEEvent(
      {
        type: "run_completed",
        payload: {
          run_id: "r1",
          agent_id: "w1",
          output_summary: "调研完成",
          duration_ms: 100,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "run_cancelled",
        payload: { run_id: "r2", agent_id: "w2" },
      } as never,
      { conversationId: CID, source: "server" },
    );

    const frames = execRuntime(useExecutionStore.getState(), mid).frames;
    expect(frames.some((f) => f.kind === "run_completed")).toBe(true);
    expect(frames.some((f) => f.kind === "run_cancelled")).toBe(true);
    expect(execRuntime(useExecutionStore.getState(), mid).status).toBe(
      "running",
    );
  });

  it("message_end 正常路径推进 terminal completed", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    useConversationStore.getState().createAssistantMessage(CID);

    dispatchSSEEvent(
      {
        type: "message_end",
        payload: {
          finish_reason: "stop",
          rounds: 1,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );

    expect(getTurnPhase(CID)).toBe("completed");
    expect(getRuntime(CID).isGenerating).toBe(false);
  });

  it("terminal completed 仍消费 detached 后的 run_*（D1 后台帧）", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    const mid = useConversationStore.getState().createAssistantMessage(CID);
    if (!mid) throw new Error("expected assistant message id");
    useExecutionStore.getState().startExecution(plan, mid);
    useExecutionStore.getState().recordFrame(
      {
        t: 1,
        kind: "run_started",
        runId: "r1",
        agentId: "w1",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      mid,
    );

    dispatchSSEEvent(
      {
        type: "message_end",
        payload: {
          finish_reason: "stop",
          rounds: 1,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );
    expect(getTurnPhase(CID)).toBe("completed");
    // 未结算 worker 时 execution 保持 running（messageStream）
    expect(execRuntime(useExecutionStore.getState(), mid).status).toBe(
      "running",
    );

    dispatchSSEEvent(
      {
        type: "execution_detached",
        payload: {
          execution_id: plan.id,
          conversation_id: CID,
          completed: 0,
          total: 2,
          host_turn_id: mid,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );
    // 收口后同连接续推（对齐 async_delivery 向量）；不得被 terminal 门禁丢弃。
    dispatchSSEEvent(
      {
        type: "run_completed",
        payload: {
          run_id: "r1",
          agent_id: "w1",
          output_summary: "调研完成",
          duration_ms: 100,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );

    const frames = execRuntime(useExecutionStore.getState(), mid).frames;
    expect(frames.some((f) => f.kind === "run_completed")).toBe(true);
    expect(
      execRuntime(useExecutionStore.getState(), mid).executionDetached,
    ).toEqual({
      execution_id: plan.id,
      conversation_id: CID,
      completed: 0,
      total: 2,
      host_turn_id: mid,
    });
  });

  it("terminal + detached running 点停止：打 stop API，不进入 stopping", async () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    const mid = useConversationStore.getState().createAssistantMessage(CID);
    if (!mid) throw new Error("expected assistant message id");
    useExecutionStore.getState().startExecution(plan, mid);
    useExecutionStore.getState().recordFrame(
      {
        t: 1,
        kind: "run_started",
        runId: "r1",
        agentId: "w1",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      mid,
    );

    dispatchSSEEvent(
      {
        type: "message_end",
        payload: {
          finish_reason: "stop",
          rounds: 1,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );
    expect(getTurnPhase(CID)).toBe("completed");
    expect(execRuntime(useExecutionStore.getState(), mid).status).toBe(
      "running",
    );

    useConversationStore.getState().stopGeneration();
    expect(getTurnPhase(CID)).toBe("completed");

    await vi.waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(`/v1/conversations/${CID}/stop`);
    });
  });

  it("terminal 且无可停 execution → 不打 stop API", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    useConversationStore.getState().createAssistantMessage(CID);
    useConversationStore.getState().setTurnPhase("completed", CID);

    useConversationStore.getState().stopGeneration();
    expect(apiPost).not.toHaveBeenCalled();
    expect(getTurnPhase(CID)).toBe("completed");
  });

  it("stopping 态收到 message_end(cancelled) → terminal stopped + exec cancelled", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    const mid = useConversationStore.getState().createAssistantMessage(CID);
    if (!mid) throw new Error("expected assistant message id");
    useExecutionStore.getState().startExecution(plan, mid);
    useConversationStore.getState().stopGeneration();
    expect(getTurnPhase(CID)).toBe("stopping");

    dispatchSSEEvent(
      {
        type: "message_end",
        payload: {
          finish_reason: "cancelled",
          rounds: 1,
        },
      } as never,
      { conversationId: CID, source: "server" },
    );

    expect(getTurnPhase(CID)).toBe("stopped");
    expect(getRuntime(CID).isGenerating).toBe(false);
    expect(execRuntime(useExecutionStore.getState(), mid).status).toBe(
      "cancelled",
    );
  });

  it("/stop 失败时回滚 streaming 并 setError 可再点停止", async () => {
    apiPost.mockRejectedValueOnce(new Error("network down"));
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    useConversationStore.getState().createAssistantMessage(CID);

    useConversationStore.getState().stopGeneration();

    await vi.waitFor(() => {
      expect(getTurnPhase(CID)).toBe("streaming");
      expect(getRuntime(CID).error).toBe("停止请求失败，引擎可能仍在运行");
      expect(typeof getRuntime(CID).retry).toBe("function");
    });
  });

  it("新回合 beginTurnPreflight 从 terminal 正确重置", () => {
    beginTurnPreflight(CID);
    enterTurnStreaming(CID);
    useConversationStore.getState().setTurnPhase("completed", CID);
    expect(getTurnPhase(CID)).toBe("completed");

    beginTurnPreflight(CID);
    expect(getTurnPhase(CID)).toBe("preflight");
    enterTurnStreaming(CID);
    expect(getTurnPhase(CID)).toBe("streaming");
  });
});

describe("stopConversation", () => {
  it("成功时返回 stopped 标志且不再吞错", async () => {
    apiPost.mockResolvedValueOnce({ stopped: true });
    await expect(stopConversation(CID)).resolves.toBe(true);
    expect(apiPost).toHaveBeenCalledWith(`/v1/conversations/${CID}/stop`);
  });

  it("失败时向上抛出", async () => {
    apiPost.mockRejectedValueOnce(new Error("boom"));
    await expect(stopConversation(CID)).rejects.toThrow("boom");
  });
});

// Sidecar vs cloud routing: see services/__tests__/stopTurn.test.ts
