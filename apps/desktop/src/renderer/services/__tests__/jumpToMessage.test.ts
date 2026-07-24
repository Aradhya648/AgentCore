import { useConversationStore } from "@/stores/conversation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { jumpToMessage } from "../messages";

const CID = "conv-jump";

beforeEach(() => {
  useConversationStore.setState({
    currentConversationId: null,
    byId: {},
    pendingFocus: null,
  });
  vi.restoreAllMocks();
});

describe("jumpToMessage", () => {
  it("focuses by client bubble id when permalink carries serverMessageId", () => {
    const store = useConversationStore.getState();
    store.switchConversation(CID);
    store.addMessage({
      id: "client-uuid",
      serverMessageId: "srv-msg-1",
      role: "assistant",
      content: "hi",
      createdAt: "",
      executionId: null,
      isStreaming: false,
    });

    void jumpToMessage(CID, "srv-msg-1");

    expect(useConversationStore.getState().byId[CID]?.messageFocus?.id).toBe(
      "client-uuid",
    );
  });

  it("still focuses when the target is already the client id", () => {
    const store = useConversationStore.getState();
    store.switchConversation(CID);
    store.addMessage({
      id: "client-uuid",
      role: "assistant",
      content: "hi",
      createdAt: "",
      executionId: null,
      isStreaming: false,
    });

    void jumpToMessage(CID, "client-uuid");

    expect(useConversationStore.getState().byId[CID]?.messageFocus?.id).toBe(
      "client-uuid",
    );
  });
});
