import { handleMessageStreamEvent } from "@/services/sse/handlers/messageStream";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beforeEach, describe, expect, it } from "vitest";

// live/fold 对齐（conformanceFold message_start 语义）：message_id 变化 ⇒ 新气泡空正文/
// 空过程时间线。live 路径复用尾部流式占位气泡时，占位上残留的上一段生命正文（如被
// 上一回合回放污染的乐观占位——重复回复 bug）必须在开流前清掉；同 message_id 的
// pause→resume 仍保留已累积正文（messageStream.resume.test.ts 覆盖的既有语义）。

const CID = "conv-new-turn-reset";
const PRIOR_MID = "srv-turn-1";
const NEW_MID = "srv-turn-2";

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  const conv = useConversationStore.getState();
  conv.switchConversation(CID);
  conv.setTurnPhase("streaming", CID);
});

function dispatchMessageStart(mid: string): void {
  handleMessageStreamEvent(
    {
      type: "message_start",
      timestamp: "",
      payload: { message_id: mid },
    },
    { conversationId: CID, source: "server" },
  );
}

describe("message_start · 换回合清残留（live 对齐 fold）", () => {
  it("陌生 message_id 复用被污染的流式占位 → 清空正文/思考/过程再开流", () => {
    const conv = useConversationStore.getState();
    conv.createAssistantMessage(CID);
    // 污染占位：模拟上一回合回放灌进来的旧正文 + 思考。
    conv.appendToLastMessage("上一回合的旧回复", CID);
    conv.appendReasoningToLastMessage("旧思考", CID);
    conv.setComposingTool({ toolName: "web_search", chars: 3 }, CID);

    dispatchMessageStart(NEW_MID);

    const msgs = getRuntime(CID).messages;
    const assistants = msgs.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1); // 复用同一占位，不重建
    const bubble = assistants[0];
    expect(bubble.content).toBe("");
    expect(bubble.reasoning ?? "").toBe("");
    expect(bubble.process ?? []).toHaveLength(0);
    expect(bubble.composingTool ?? null).toBeNull();
    expect(bubble.isStreaming).toBe(true);
    expect(bubble.serverMessageId).toBe(NEW_MID);
    expect(getRuntime(CID).isGenerating).toBe(true);
  });

  it("干净占位无残留 → no-op（对象身份不换，避免无谓重渲染）", () => {
    const conv = useConversationStore.getState();
    conv.createAssistantMessage(CID);
    const before = getRuntime(CID).messages.at(-1);

    dispatchMessageStart(NEW_MID);

    const after = getRuntime(CID).messages.at(-1);
    expect(after?.content).toBe("");
    // serverMessageId 盖章会换对象；断言正文字段未被 reset 动作误改即可。
    expect(after?.serverMessageId).toBe(NEW_MID);
    expect(before?.content).toBe("");
  });

  it("同 message_id 的 pause→resume 保留已累积正文（既有语义不回归）", () => {
    const conv = useConversationStore.getState();
    conv.createAssistantMessage(CID);
    conv.setServerMessageIdOnLastMessage(PRIOR_MID, CID);
    conv.appendToLastMessage("已流式的一半回复", CID);
    conv.finalizeLastMessage(CID); // 挂起收口：isStreaming=false

    dispatchMessageStart(PRIOR_MID);

    const bubble = getRuntime(CID).messages.at(-1);
    expect(bubble?.content).toBe("已流式的一半回复");
    expect(bubble?.isStreaming).toBe(true);
  });

  it("上一回合已收口（非流式）→ 新建空气泡，旧气泡正文不动", () => {
    const conv = useConversationStore.getState();
    conv.createAssistantMessage(CID);
    conv.setServerMessageIdOnLastMessage(PRIOR_MID, CID);
    conv.appendToLastMessage("上一回合完整回复", CID);
    conv.finalizeLastMessage(CID);
    // 同连接下一回合：terminal 拨回 streaming 的入口在 handler 内部。
    conv.setTurnPhase("completed", CID);

    dispatchMessageStart(NEW_MID);

    const assistants = getRuntime(CID).messages.filter(
      (m) => m.role === "assistant",
    );
    expect(assistants).toHaveLength(2);
    expect(assistants[0].content).toBe("上一回合完整回复");
    expect(assistants[1].content).toBe("");
    expect(assistants[1].isStreaming).toBe(true);
    expect(assistants[1].serverMessageId).toBe(NEW_MID);
  });
});
