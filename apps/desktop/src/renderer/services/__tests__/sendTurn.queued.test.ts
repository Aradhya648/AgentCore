import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// sendTurn × 发送即有流：POST 恒 SSE；排队态由 turn_queued → dispatch toast，
// 同连接续流——不再有 SendOutcome.queued / watchQueuedTurn。
vi.mock("@/hooks/useConversations", () => ({
  getConversations: vi.fn(() => []),
  bumpConversationCache: vi.fn(),
  restoreConversationCache: vi.fn(),
}));
vi.mock("@/services/sidecarRouting", () => ({
  resolveSidecarRoot: vi.fn(() => Promise.resolve(null)),
  buildSidecarHistory: vi.fn(() => []),
}));
vi.mock("@/services/sidecarHealth", () => ({
  probeSidecar: vi.fn(),
  markSidecarUnhealthy: vi.fn(),
  clearSidecarHealth: vi.fn(),
}));
vi.mock("@/services/streamConversation", () => ({
  attachConversation: vi.fn(),
  streamConversation: vi.fn(),
  regenerateConversation: vi.fn(),
  resumeConversation: vi.fn(),
}));
vi.mock("@/services/streamConversationViaSidecar", () => ({
  streamConversationViaSidecar: vi.fn(),
  resumeConversationViaSidecar: vi.fn(),
}));
vi.mock("@/services/messages", () => ({ loadLatestWindow: vi.fn() }));
vi.mock("@/lib/toast", () => ({
  notifyInfo: vi.fn(),
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));
vi.mock("@/services/turns/recovery", () => ({
  rejoinLiveTurn: vi.fn(),
  attachOnOpen: vi.fn(),
  markGhostInterrupted: vi.fn(),
  settleCloudRunningAssistant: vi.fn(),
}));

import { notifyInfo } from "@/lib/toast";
import { streamConversation } from "@/services/streamConversation";
import { rejoinLiveTurn } from "@/services/turns/recovery";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { sendTurn } from "../turns/stream";

const streamMock = vi.mocked(streamConversation);
const rejoinMock = vi.mocked(rejoinLiveTurn);
const notifyInfoMock = vi.mocked(notifyInfo);

const CID = "conv-send-queued";

function spec() {
  return {
    conversationId: CID,
    content: "第二问",
    attachments: [],
    optimisticUserId: "opt-u2",
  };
}

function seedOptimisticUser(): void {
  useConversationStore.getState().addMessage(
    {
      id: "opt-u2",
      role: "user",
      content: "第二问",
      createdAt: "",
      executionId: null,
      isStreaming: false,
    },
    CID,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  seedOptimisticUser();
});

afterEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
});

describe("sendTurn — 发送即有流（无 202 / 无守望）", () => {
  it("streamConversation resolve → 正常收口，不 toast、不 rejoin", async () => {
    streamMock.mockResolvedValue(undefined);

    await sendTurn(spec());

    expect(streamMock).toHaveBeenCalledTimes(1);
    expect(rejoinMock).not.toHaveBeenCalled();
    expect(notifyInfoMock).not.toHaveBeenCalled();
    expect(getRuntime(CID).error).toBeNull();
  });

  it("流式路径打开助手占位（排队等待与空闲开跑共用）", async () => {
    streamMock.mockResolvedValue(undefined);

    await sendTurn(spec());

    const assistants = getRuntime(CID).messages.filter(
      (m) => m.role === "assistant",
    );
    expect(assistants.length).toBeGreaterThanOrEqual(1);
  });
});
