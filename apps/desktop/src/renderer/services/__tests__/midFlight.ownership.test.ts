import { notifyInfo } from "@/lib/toast";
import { dispatchSSEEvent, flushPendingContent } from "@/services/sse/dispatch";
import { handleMessageStreamEvent } from "@/services/sse/handlers/messageStream";
import { sendMidFlightMessage } from "@/services/turns/midFlight";
import {
  claimPrimaryStream,
  releasePrimaryStream,
  resetStreamOwnershipForTests,
} from "@/services/turns/streamOwnership";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import type { SSEEvent } from "@/types/events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/toast", () => ({
  notifyInfo: vi.fn(),
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));

const notifyInfoMock = vi.mocked(notifyInfo);
const CID = "conv-mf-race";

/** 可控 SSE 体：测试里按帧 push，模拟双连接时序。 */
function controllableSse(): {
  response: Response;
  push: (event: SSEEvent) => void;
  close: () => void;
  error: (err?: Error) => void;
} {
  const enc = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    push(event) {
      controller.enqueue(enc.encode(`data: ${JSON.stringify(event)}\n\n`));
    },
    close() {
      controller.close();
    },
    error(err = new DOMException("Aborted", "AbortError")) {
      controller.error(err);
    },
  };
}

function ev(
  type: SSEEvent["type"],
  payload: Record<string, unknown> = {},
): SSEEvent {
  return { type, timestamp: "", payload } as SSEEvent;
}

beforeEach(() => {
  vi.clearAllMocks();
  resetStreamOwnershipForTests();
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  useConversationStore.getState().switchConversation(CID);
  useConversationStore.getState().setTurnPhase("streaming", CID);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetStreamOwnershipForTests();
  useConversationStore.setState({ currentConversationId: null, byId: {} });
});

describe("midFlight · 主路门 + store 断言", () => {
  it("经典排队：主路持有时缓冲 message_start，释放后才插用户气泡并开 turn2", async () => {
    const turn1Token = claimPrimaryStream(CID);
    const conv = useConversationStore.getState();
    conv.addMessage(
      {
        id: "u1",
        role: "user",
        content: "第一问",
        createdAt: "",
        executionId: null,
        isStreaming: false,
      },
      CID,
    );
    conv.createAssistantMessage(CID);
    conv.appendToLastMessage("turn1-正文", CID);
    conv.setServerMessageIdOnLastMessage("srv-turn1", CID);

    const sse = controllableSse();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(sse.response)),
    );

    const pending = sendMidFlightMessage(CID, "第二问");
    await vi.waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalled();
    });

    sse.push(
      ev("turn_queued", {
        queue_id: "q1",
        position: 1,
        queue_depth: 1,
        conversation_id: CID,
      }),
    );
    await vi.waitFor(() => {
      expect(notifyInfoMock).toHaveBeenCalledWith(
        expect.stringContaining("已排队"),
      );
    });

    // drain 边界交错：conn2 已到 message_start，但 turn1 主路未释放
    sse.push(ev("message_start", { message_id: "srv-turn2" }));
    await new Promise((r) => setTimeout(r, 10));

    // 不变式 c：turn1 正文未被 resetAssistant 清掉
    const midRace = getRuntime(CID).messages;
    const turn1Assistant = midRace.find(
      (m) => m.role === "assistant" && m.serverMessageId === "srv-turn1",
    );
    expect(turn1Assistant?.content).toBe("turn1-正文");
    expect(
      midRace.some((m) => m.role === "user" && m.content === "第二问"),
    ).toBe(false);

    // turn1 收口帧仍走 conn1 dispatch（不丢）
    handleMessageStreamEvent(
      ev("message_end", {
        finish_reason: "end_turn",
        cost: {
          input: 1,
          cached: 0,
          output: 1,
          total: 2,
          currency: "USD",
          pricing_source: "curated",
        },
      }),
      { conversationId: CID, source: "server" },
    );
    expect(getRuntime(CID).messages.at(-1)?.cost?.total).toBe(2);

    releasePrimaryStream(CID, turn1Token);
    await vi.waitFor(() => {
      expect(
        getRuntime(CID).messages.some(
          (m) => m.role === "user" && m.content === "第二问",
        ),
      ).toBe(true);
    });

    // 放行后：用户气泡 + turn2 开流
    const after = getRuntime(CID).messages;
    const turn2 = after.find(
      (m) => m.role === "assistant" && m.serverMessageId === "srv-turn2",
    );
    expect(turn2).toBeTruthy();
    // turn1 定稿仍在
    expect(after.find((m) => m.serverMessageId === "srv-turn1")?.content).toBe(
      "turn1-正文",
    );

    sse.push(ev("content_delta", { delta: "turn2-答" }));
    sse.push(ev("message_end", { finish_reason: "end_turn" }));
    sse.close();
    await expect(pending).resolves.toMatchObject({
      kind: "queued",
      position: 1,
    });
    flushPendingContent(CID);
    expect(
      getRuntime(CID).messages.find((m) => m.serverMessageId === "srv-turn2")
        ?.content,
    ).toContain("turn2");
  });

  it("排队等待中 Abort：丢弃缓冲、无 turn2 用户气泡；result=queued（detached）", async () => {
    const turn1Token = claimPrimaryStream(CID);
    const parentAc = new AbortController();
    useConversationStore.getState().setAbort(parentAc, CID);
    useConversationStore.getState().createAssistantMessage(CID);

    const sse = controllableSse();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(sse.response)),
    );

    const pending = sendMidFlightMessage(CID, "排队后停止");
    await vi.waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalled();
    });

    sse.push(
      ev("turn_queued", {
        queue_id: "q1",
        position: 1,
        queue_depth: 1,
        conversation_id: CID,
      }),
    );
    await vi.waitFor(() => {
      expect(notifyInfoMock).toHaveBeenCalled();
    });
    sse.push(ev("message_start", { message_id: "srv-should-not-land" }));
    await new Promise((r) => setTimeout(r, 10));

    // 停止 turn1 → 联动 abort midFlight；error 流使泵跳出（mock fetch 不绑 signal）
    parentAc.abort();
    sse.error(new DOMException("Aborted", "AbortError"));

    await expect(pending).resolves.toMatchObject({ kind: "queued" });
    expect(
      getRuntime(CID).messages.some(
        (m) => m.role === "user" && m.content === "排队后停止",
      ),
    ).toBe(false);
    expect(
      getRuntime(CID).messages.some(
        (m) => m.serverMessageId === "srv-should-not-land",
      ),
    ).toBe(false);

    releasePrimaryStream(CID, turn1Token);
  });

  it("release 与 abort 同刻：waiter 同步 flush 须丢缓冲，不得插用户气泡 / fold message_start", async () => {
    const turn1Token = claimPrimaryStream(CID);
    const parentAc = new AbortController();
    useConversationStore.getState().setAbort(parentAc, CID);
    useConversationStore.getState().createAssistantMessage(CID);

    const sse = controllableSse();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(sse.response)),
    );

    const pending = sendMidFlightMessage(CID, "同刻停止");
    await vi.waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalled();
    });

    sse.push(
      ev("turn_queued", {
        queue_id: "q1",
        position: 1,
        queue_depth: 1,
        conversation_id: CID,
      }),
    );
    await vi.waitFor(() => {
      expect(notifyInfoMock).toHaveBeenCalled();
    });
    sse.push(ev("message_start", { message_id: "srv-race-abort-flush" }));
    await new Promise((r) => setTimeout(r, 10));

    // 关键缝：abort 已置位，紧接着 turn1 finally 同步 release → waiter 同步唤 flush
    parentAc.abort();
    releasePrimaryStream(CID, turn1Token);
    expect(
      getRuntime(CID).messages.some(
        (m) => m.role === "user" && m.content === "同刻停止",
      ),
    ).toBe(false);
    expect(
      getRuntime(CID).messages.some(
        (m) => m.serverMessageId === "srv-race-abort-flush",
      ),
    ).toBe(false);

    sse.error(new DOMException("Aborted", "AbortError"));
    await expect(pending).resolves.toMatchObject({ kind: "queued" });
    expect(
      getRuntime(CID).messages.some(
        (m) => m.role === "user" && m.content === "同刻停止",
      ),
    ).toBe(false);
  });

  it("协调插话：user_interjection 即时 dispatch，不经主路缓冲", async () => {
    const turn1Token = claimPrimaryStream(CID);
    const sse = controllableSse();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(sse.response)),
    );

    const pending = sendMidFlightMessage(CID, "插一句");
    await vi.waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalled();
    });

    sse.push(
      ev("user_interjection", {
        interjection_id: "ij1",
        execution_id: "ex1",
        content: "插一句",
        status: "received",
      }),
    );
    sse.close();

    await expect(pending).resolves.toEqual({
      kind: "received",
      interjectionId: "ij1",
    });
    // 主路仍持有也不妨碍插话短流收口
    expect(getRuntime(CID).messages.some((m) => m.content === "插一句")).toBe(
      false,
    );
    releasePrimaryStream(CID, turn1Token);
  });
});

describe("同连接 turn_queued → message_start → 收口（dispatch 全链）", () => {
  it("主路空闲时 turn_queued 后自然续流，正文落在新回合助手气泡", () => {
    // 无 primary = 空闲（idle send 同连接路径）
    const conv = useConversationStore.getState();
    conv.addMessage(
      {
        id: "u-q",
        role: "user",
        content: "排队问",
        createdAt: "",
        executionId: null,
        isStreaming: false,
      },
      CID,
    );
    conv.createAssistantMessage(CID);

    dispatchSSEEvent(
      ev("turn_queued", {
        queue_id: "q1",
        position: 1,
        queue_depth: 1,
        conversation_id: CID,
      }),
      { conversationId: CID, source: "server" },
    );
    expect(notifyInfoMock).toHaveBeenCalledWith("已排队，当前回合结束后处理");

    dispatchSSEEvent(ev("message_start", { message_id: "m-q" }), {
      conversationId: CID,
      source: "server",
    });
    dispatchSSEEvent(ev("content_delta", { delta: "续流正文" }), {
      conversationId: CID,
      source: "server",
    });
    flushPendingContent(CID);
    dispatchSSEEvent(
      ev("message_end", {
        finish_reason: "end_turn",
        cost: {
          input: 10,
          cached: 0,
          output: 5,
          total: 15,
          currency: "USD",
          pricing_source: "curated",
        },
      }),
      { conversationId: CID, source: "server" },
    );

    const last = getRuntime(CID).messages.at(-1);
    expect(last?.role).toBe("assistant");
    expect(last?.serverMessageId).toBe("m-q");
    expect(last?.content).toBe("续流正文");
    expect(last?.isStreaming).toBe(false);
    expect(last?.cost?.total).toBe(15);
    expect(getRuntime(CID).isGenerating).toBe(false);
  });
});
