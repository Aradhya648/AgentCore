import { useConversationStore } from "@/stores/conversation";
import type { SidecarUnsyncedTurnSummary } from "@shared/sidecar-contract";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/streamConversation", () => ({
  dispatchSSEEvent: vi.fn(),
  flushPendingContent: vi.fn(),
  flushPendingFrames: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  api: {
    get: vi.fn(async () => ({
      live_running: false,
      paused: [],
      pending_interactions: [],
    })),
  },
}));

import { dispatchSSEEvent } from "@/services/streamConversation";
import {
  clearActiveSidecarTurn,
  getActiveSidecarTarget,
  setActiveSidecarTurn,
} from "../sidecarRouting";
import { projectUnsyncedTurns } from "../turns/projectUnsynced";
import { attachSidecarTurn } from "../turns/sidecarAttach";

const CID = "conv-sidecar-recover";
const dispatchMock = vi.mocked(dispatchSSEEvent);

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  clearActiveSidecarTurn(CID);
  dispatchMock.mockClear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function unsyncedReady(
  over: Partial<SidecarUnsyncedTurnSummary> = {},
): SidecarUnsyncedTurnSummary {
  return {
    user_message_id: "u-ready",
    user_message: "prior q",
    message_id: "a-ready",
    trace_id: "t".repeat(32),
    phase: "ready",
    updated_at: 100,
    content: "prior answer",
    reasoning_content: null,
    citations: [],
    runs: { events: [], finish_reason: "stop" },
    finish_reason: "stop",
    input_tokens: 1,
    output_tokens: 2,
    reasoning_tokens: 0,
    cache_hit_tokens: 0,
    cache_miss_tokens: 0,
    ...over,
  };
}

describe("projectUnsyncedTurns (D5)", () => {
  it("projects ready rows with synced_pending and skips duplicate ids", () => {
    const store = useConversationStore.getState();
    store.switchConversation(CID);
    store.addMessage(
      {
        id: "u-ready",
        role: "user",
        content: "already from cloud",
        createdAt: "2026-01-01T00:00:00Z",
        executionId: null,
        isStreaming: false,
      },
      CID,
    );

    projectUnsyncedTurns(CID, [
      unsyncedReady(),
      unsyncedReady({
        user_message_id: "u-new",
        message_id: "a-new",
        user_message: "new q",
        content: "new a",
        updated_at: 200,
      }),
    ]);

    const msgs = useConversationStore.getState().byId[CID].messages;
    expect(msgs.filter((m) => m.id === "u-ready")).toHaveLength(1);
    expect(msgs.find((m) => m.id === "u-new")?.content).toBe("new q");
    expect(msgs.find((m) => m.id === "a-new")?.content).toBe("new a");
    expect(msgs.find((m) => m.id === "u-new")?.syncStatus).toBe(
      "synced_pending",
    );
  });

  it("marks open ghost as interrupted incomplete", () => {
    useConversationStore.getState().switchConversation(CID);
    projectUnsyncedTurns(CID, [
      unsyncedReady({
        user_message_id: "u-open",
        message_id: "a-open",
        phase: "open",
        content: "partial",
        finish_reason: null,
        runs: null,
      }),
    ]);
    const assistant = useConversationStore
      .getState()
      .byId[CID].messages.find((m) => m.id === "a-open");
    expect(assistant?.status).toBe("incomplete");
    expect(assistant?.isStreaming).toBe(false);
    expect(assistant?.finishReason).toBe("interrupted");
  });
});

describe("attachSidecarTurn (D4)", () => {
  it("synthesizes user row, setActive before fold, replays terminal", async () => {
    useConversationStore.getState().switchConversation(CID);

    const attachMock = vi.fn(async () => ({
      attached: true as const,
      turnId: "turn-live",
      rootId: "root-1",
      subpath: "",
      kind: "start" as const,
      userMessageId: "u-live",
      userMessage: "live q",
      traceId: "f".repeat(32),
      events: [
        {
          type: "message_start",
          timestamp: "t0",
          payload: { message_id: "a-live" },
        },
        {
          type: "content_delta",
          timestamp: "t1",
          payload: { delta: "hello" },
        },
        {
          type: "message_end",
          timestamp: "t2",
          payload: { finish_reason: "stop" },
        },
      ],
    }));

    vi.stubGlobal("window", {
      sidecarApi: {
        attach: attachMock,
        onEvent: () => () => {},
        cancel: vi.fn(),
      },
    });

    const ok = await attachSidecarTurn(CID);
    expect(ok).toBe(true);
    expect(attachMock).toHaveBeenCalledWith({ conversationId: CID });

    const msgs = useConversationStore.getState().byId[CID].messages;
    expect(msgs.some((m) => m.id === "u-live" && m.content === "live q")).toBe(
      true,
    );
    expect(dispatchMock.mock.calls.map((c) => c[0].type)).toEqual([
      "message_start",
      "content_delta",
      "message_end",
    ]);
    expect(getActiveSidecarTarget(CID)).toBeNull();
    expect(msgs.find((m) => m.id === "u-live")?.syncStatus).toBe(
      "synced_pending",
    );
  });

  it("skips when already generating (same-session guard)", async () => {
    const store = useConversationStore.getState();
    store.switchConversation(CID);
    store.setGenerating(true, CID);
    const attach = vi.fn();
    vi.stubGlobal("window", {
      sidecarApi: { attach, onEvent: () => () => {}, cancel: vi.fn() },
    });
    expect(await attachSidecarTurn(CID)).toBe(true);
    expect(attach).not.toHaveBeenCalled();
  });

  it("attached:false does not leave generating hung (fact-driven re-query)", async () => {
    useConversationStore.getState().switchConversation(CID);

    vi.stubGlobal("window", {
      __WEB__: false,
      sidecarApi: {
        attach: vi.fn(async () => ({ attached: false })),
        recovery: vi.fn(async () => ({
          liveRunning: false,
          unsynced: [],
          paused: [],
        })),
        onEvent: () => () => {},
        cancel: vi.fn(),
      },
    });

    const ok = await attachSidecarTurn(CID);
    expect(ok).toBe(false);
    expect(
      useConversationStore.getState().byId[CID]?.isGenerating ?? false,
    ).toBe(false);
  });
});

describe("clearActiveSidecarTurn turnId match", () => {
  it("does not clear when turnId mismatches", () => {
    setActiveSidecarTurn(CID, "r1", "", "turn-A");
    clearActiveSidecarTurn(CID, "turn-B");
    expect(getActiveSidecarTarget(CID)?.rootId).toBe("r1");
    clearActiveSidecarTurn(CID, "turn-A");
    expect(getActiveSidecarTarget(CID)).toBeNull();
  });
});
