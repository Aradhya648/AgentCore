import { handleMessageStreamEvent } from "@/services/sse/handlers/messageStream";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import {
  type ExecutionPlan,
  execRuntime,
  useExecutionStore,
} from "@/stores/execution";
import { beforeEach, describe, expect, it } from "vitest";

const CID = "conv-resume-id";
const SERVER_MID = "srv-turn-1";

const plan: ExecutionPlan = {
  id: "exec-1",
  planType: "multi_agent",
  taskSummary: "t",
  agents: [{ id: "a1", role: "r" }],
  runs: [{ id: "r1", agentId: "a1", task: "t", dependsOn: [] }],
};

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  useExecutionStore.setState({ byId: {} });
});

function seedPausedTurn(): string {
  const conv = useConversationStore.getState();
  conv.switchConversation(CID);
  conv.addMessage({
    id: "u1",
    role: "user",
    content: "go",
    createdAt: "",
    executionId: null,
    isStreaming: false,
  });
  const clientId = conv.createAssistantMessage(CID);
  conv.setServerMessageIdOnLastMessage(SERVER_MID, CID);
  useExecutionStore.getState().startExecution(plan, SERVER_MID);
  useExecutionStore.getState().setStatus("paused", SERVER_MID);
  conv.finalizeLastMessage(CID);
  return clientId;
}

describe("message_start resume identity (Option A)", () => {
  it("does not delete the paused bubble; flips streaming and keeps one assistant", () => {
    const clientId = seedPausedTurn();
    const before = getRuntime(CID).messages.filter(
      (m) => m.role === "assistant",
    ).length;

    handleMessageStreamEvent(
      {
        type: "message_start",
        timestamp: "",
        payload: { message_id: SERVER_MID, trace_id: "tr1" },
      },
      { conversationId: CID, source: "server" },
    );

    const msgs = getRuntime(CID).messages;
    const assistants = msgs.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(before);
    expect(assistants[0].id).toBe(clientId);
    expect(assistants[0].serverMessageId).toBe(SERVER_MID);
    expect(assistants[0].isStreaming).toBe(true);
    expect(getRuntime(CID).isGenerating).toBe(true);
    // Execution stays under the server turn id (aligned on first stamp).
    expect(execRuntime(useExecutionStore.getState(), SERVER_MID).plan?.id).toBe(
      "exec-1",
    );
    expect(execRuntime(useExecutionStore.getState(), clientId).plan).toBeNull();
  });

  it("is idempotent when the bubble is already streaming", () => {
    seedPausedTurn();
    useConversationStore.getState().resumePausedAssistant(SERVER_MID, CID);

    handleMessageStreamEvent(
      {
        type: "message_start",
        timestamp: "",
        payload: { message_id: SERVER_MID },
      },
      { conversationId: CID, source: "server" },
    );

    expect(
      getRuntime(CID).messages.filter((m) => m.role === "assistant"),
    ).toHaveLength(1);
    expect(
      getRuntime(CID).messages.find((m) => m.role === "assistant")?.isStreaming,
    ).toBe(true);
  });
});
