import { notifyInfo } from "@/lib/toast";
import { handleMessageStreamEvent } from "@/services/sse/handlers/messageStream";
import { useConversationStore } from "@/stores/conversation";
import { useQueuedTurnsStore } from "@/stores/queuedTurns";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/toast", () => ({
  notifyInfo: vi.fn(),
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));

const notifyInfoMock = vi.mocked(notifyInfo);
const CID = "conv-turn-queued";

beforeEach(() => {
  vi.clearAllMocks();
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  useQueuedTurnsStore.setState({ byConversation: {} });
  useConversationStore.getState().switchConversation(CID);
  useConversationStore.getState().setTurnPhase("streaming", CID);
});

afterEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  useQueuedTurnsStore.setState({ byConversation: {} });
});

describe("turn_queued · live 对齐 fold（EPHEMERAL toast）", () => {
  it("呈现既有「已排队」toast（单条）", () => {
    handleMessageStreamEvent(
      {
        type: "turn_queued",
        timestamp: "",
        payload: {
          queue_id: "q1",
          position: 1,
          queue_depth: 1,
          conversation_id: CID,
        },
      },
      { conversationId: CID, source: "server" },
    );
    expect(notifyInfoMock).toHaveBeenCalledWith("已排队，当前回合结束后处理");
  });

  it("多条排队时带位次", () => {
    handleMessageStreamEvent(
      {
        type: "turn_queued",
        timestamp: "",
        payload: {
          queue_id: "q2",
          position: 2,
          queue_depth: 3,
          conversation_id: CID,
        },
      },
      { conversationId: CID, source: "server" },
    );
    expect(notifyInfoMock).toHaveBeenCalledWith(
      expect.stringContaining("第 2/3 条"),
    );
  });

  it("degraded_from=steer → 额外 toast 说明已改为排队", () => {
    handleMessageStreamEvent(
      {
        type: "turn_queued",
        timestamp: "",
        payload: {
          queue_id: "q3",
          position: 1,
          queue_depth: 1,
          conversation_id: CID,
          degraded_from: "steer",
        },
      },
      { conversationId: CID, source: "server" },
    );
    expect(notifyInfoMock).toHaveBeenCalledWith("已排队，当前回合结束后处理");
    expect(notifyInfoMock).toHaveBeenCalledWith(
      "当前无法插入，已改为排队，将在本回合结束后发送",
    );
  });
});

describe("turn_steer_accepted · live toast", () => {
  it("呈现「已插入，下一工具步生效」", () => {
    handleMessageStreamEvent(
      {
        type: "turn_steer_accepted",
        timestamp: "",
        payload: {
          steer_id: "steer-1",
          conversation_id: CID,
          content: "改成中文",
          pending: 1,
        },
      },
      { conversationId: CID, source: "server" },
    );
    expect(notifyInfoMock).toHaveBeenCalledWith("已插入，下一工具步生效");
  });
});

describe("turn_queue_cancelled · 清排队 UI", () => {
  it("移除 store 项与乐观用户气泡", () => {
    useConversationStore.getState().addMessage(
      {
        id: "user-q",
        role: "user",
        content: "queued",
        createdAt: new Date().toISOString(),
        executionId: null,
        isStreaming: false,
      },
      CID,
    );
    useQueuedTurnsStore.getState().upsert({
      queueId: "q-cancel",
      conversationId: CID,
      messageId: "user-q",
      content: "queued",
      position: 1,
      queueDepth: 1,
    });

    handleMessageStreamEvent(
      {
        type: "turn_queue_cancelled",
        timestamp: "",
        payload: { queue_id: "q-cancel", conversation_id: CID },
      },
      { conversationId: CID, source: "server" },
    );

    expect(useQueuedTurnsStore.getState().list(CID)).toEqual([]);
    expect(
      useConversationStore
        .getState()
        .byId[CID]?.messages.find((m) => m.id === "user-q"),
    ).toBeUndefined();
  });

  it("本地已清后 SSE 幂等 no-op", () => {
    handleMessageStreamEvent(
      {
        type: "turn_queue_cancelled",
        timestamp: "",
        payload: { queue_id: "missing", conversation_id: CID },
      },
      { conversationId: CID, source: "server" },
    );
    expect(useQueuedTurnsStore.getState().list(CID)).toEqual([]);
  });
});
