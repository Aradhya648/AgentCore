import {
  discardPendingContent,
  flushPendingContent,
  queueContentDelta,
  queueReasoningDelta,
} from "@/services/sse/contentBuffer";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const CONV = "conv-buffer-test";
const store = () => useConversationStore.getState();
const rt = () => getRuntime(CONV);

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", () => 1);
  vi.stubGlobal("cancelAnimationFrame", () => {});
  useConversationStore.setState({ currentConversationId: CONV, byId: {} });
  store().switchConversation(CONV);
  store().createAssistantMessage(CONV);
});

afterEach(() => {
  flushPendingContent(CONV);
  vi.unstubAllGlobals();
});

describe("contentBuffer FIFO flush", () => {
  it("preserves reasoning-before-content order when both queue before flush", () => {
    queueReasoningDelta(CONV, "用户问的是能力边界。");
    queueContentDelta(CONV, "不能");
    flushPendingContent(CONV);

    const msg = rt().messages[0];
    expect(msg.reasoning).toBe("用户问的是能力边界。");
    expect(msg.content).toBe("不能");
    expect(msg.process).toEqual([
      { kind: "reasoning", text: "用户问的是能力边界。" },
      { kind: "content", text: "不能" },
    ]);
  });

  it("coalesces consecutive same-kind deltas into one chunk before flush", () => {
    queueReasoningDelta(CONV, "先");
    queueReasoningDelta(CONV, "想");
    queueContentDelta(CONV, "答");
    queueContentDelta(CONV, "案");
    flushPendingContent(CONV);

    const msg = rt().messages[0];
    expect(msg.process).toEqual([
      { kind: "reasoning", text: "先想" },
      { kind: "content", text: "答案" },
    ]);
  });

  it("does not reorder interleaved chunks (regression: old buckets flushed content first)", () => {
    queueReasoningDelta(CONV, "R1");
    queueContentDelta(CONV, "C1");
    queueReasoningDelta(CONV, "R2");
    queueContentDelta(CONV, "C2");
    flushPendingContent(CONV);

    expect(rt().messages[0].process?.map((s) => s.kind)).toEqual([
      "reasoning",
      "content",
      "reasoning",
      "content",
    ]);
    expect(rt().messages[0].reasoning).toBe("R1R2");
    expect(rt().messages[0].content).toBe("C1C2");
  });
});

describe("discardPendingContent", () => {
  it("drops only buffered content chunks, keeps reasoning in arrival order", () => {
    queueReasoningDelta(CONV, "r1");
    queueContentDelta(CONV, "bad draft");
    queueReasoningDelta(CONV, "r2");
    discardPendingContent(CONV);
    flushPendingContent(CONV);

    const msg = rt().messages[0];
    expect(msg.content).toBe("");
    expect(msg.reasoning).toBe("r1r2");
    expect(msg.process).toEqual([{ kind: "reasoning", text: "r1r2" }]);
  });

  it("cancels pending frame when only content was buffered", () => {
    queueContentDelta(CONV, "draft");
    discardPendingContent(CONV);
    flushPendingContent(CONV);

    expect(rt().messages[0].content).toBe("");
    expect(rt().messages[0].process).toBeUndefined();
  });
});
