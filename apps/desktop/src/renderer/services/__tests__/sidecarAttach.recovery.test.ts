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
import { resetSidecarEventPumpForTests } from "../sidecarEventPump";
import {
  clearActiveSidecarTurn,
  getActiveSidecarTarget,
  setActiveSidecarTurn,
} from "../sidecarRouting";
import { projectUnsyncedTurns } from "../turns/projectUnsynced";
import {
  attachSidecarTurn,
  resetSidecarAttachInFlightForTests,
} from "../turns/sidecarAttach";

const CID = "conv-sidecar-recover";
const dispatchMock = vi.mocked(dispatchSSEEvent);

type EventPush = {
  conversationId: string;
  turnId: string;
  event: unknown;
};

let onEventCb: ((push: EventPush) => void) | null;
let onEventCalls: number;

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  clearActiveSidecarTurn(CID);
  resetSidecarEventPumpForTests();
  resetSidecarAttachInFlightForTests();
  dispatchMock.mockClear();
  onEventCb = null;
  onEventCalls = 0;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubSidecarApi(over: {
  attach?: ReturnType<typeof vi.fn>;
  recovery?: ReturnType<typeof vi.fn>;
  cancel?: ReturnType<typeof vi.fn>;
}): void {
  vi.stubGlobal("window", {
    __WEB__: false,
    sidecarApi: {
      attach: over.attach ?? vi.fn(async () => ({ attached: false })),
      recovery:
        over.recovery ??
        vi.fn(async () => ({
          liveRunning: false,
          unsynced: [],
          paused: [],
        })),
      cancel: over.cancel ?? vi.fn(),
      onEvent: vi.fn((cb: (push: EventPush) => void) => {
        onEventCalls += 1;
        onEventCb = cb;
        return () => {
          if (onEventCb === cb) onEventCb = null;
        };
      }),
    },
  });
}

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

function attachLiveResponse(over: Record<string, unknown> = {}) {
  return {
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

    const attachMock = vi.fn(async () => attachLiveResponse());
    stubSidecarApi({ attach: attachMock });

    const ok = await attachSidecarTurn(CID);
    expect(ok).toBe(true);
    expect(attachMock).toHaveBeenCalledWith({ conversationId: CID });
    expect(onEventCalls).toBe(1);

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
    stubSidecarApi({ attach });
    expect(await attachSidecarTurn(CID)).toBe(true);
    expect(attach).not.toHaveBeenCalled();
    expect(onEventCalls).toBe(0);
  });

  it("attached:false does not leave generating hung (fact-driven re-query)", async () => {
    useConversationStore.getState().switchConversation(CID);

    stubSidecarApi({
      attach: vi.fn(async () => ({ attached: false })),
      recovery: vi.fn(async () => ({
        liveRunning: false,
        unsynced: [],
        paused: [],
      })),
    });

    const ok = await attachSidecarTurn(CID);
    expect(ok).toBe(false);
    expect(
      useConversationStore.getState().byId[CID]?.isGenerating ?? false,
    ).toBe(false);
  });

  it("concurrent dual attach / hydrate twice → one IPC + one content_delta dispatch", async () => {
    useConversationStore.getState().switchConversation(CID);

    let releaseAttach!: (v: ReturnType<typeof attachLiveResponse>) => void;
    const attachGate = new Promise<ReturnType<typeof attachLiveResponse>>(
      (resolve) => {
        releaseAttach = resolve;
      },
    );
    const attachMock = vi.fn(() => attachGate);
    stubSidecarApi({ attach: attachMock });

    const p1 = attachSidecarTurn(CID);
    const p2 = attachSidecarTurn(CID);
    expect(attachMock).toHaveBeenCalledTimes(1);

    releaseAttach(
      attachLiveResponse({
        events: [
          {
            type: "message_start",
            timestamp: "t0",
            payload: { message_id: "a-live" },
          },
          {
            type: "content_delta",
            timestamp: "t1",
            payload: { delta: "once" },
          },
          {
            type: "message_end",
            timestamp: "t2",
            payload: { finish_reason: "stop" },
          },
        ],
      }),
    );

    await expect(Promise.all([p1, p2])).resolves.toEqual([true, true]);
    expect(onEventCalls).toBe(1);
    const deltas = dispatchMock.mock.calls.filter(
      (c) => c[0].type === "content_delta",
    );
    expect(deltas).toHaveLength(1);
    expect(deltas[0][0].payload).toEqual({ delta: "once" });
  });

  it("live content_delta after attach is dispatched once (single pump)", async () => {
    useConversationStore.getState().switchConversation(CID);

    let resolveDone!: () => void;
    const turnDone = new Promise<void>((r) => {
      resolveDone = r;
    });

    const attachMock = vi.fn(async () => {
      // Snapshot without terminal — live tail must finish the turn.
      queueMicrotask(() => {
        onEventCb?.({
          conversationId: CID,
          turnId: "turn-live",
          event: {
            type: "content_delta",
            timestamp: "t-live",
            payload: { delta: "tok" },
          },
        });
        onEventCb?.({
          conversationId: CID,
          turnId: "turn-live",
          event: {
            type: "message_end",
            timestamp: "t-end",
            payload: { finish_reason: "stop" },
          },
        });
        resolveDone();
      });
      return attachLiveResponse({
        events: [
          {
            type: "message_start",
            timestamp: "t0",
            payload: { message_id: "a-live" },
          },
        ],
      });
    });
    stubSidecarApi({ attach: attachMock });

    const ok = await attachSidecarTurn(CID);
    await turnDone;
    expect(ok).toBe(true);
    expect(onEventCalls).toBe(1);
    const deltas = dispatchMock.mock.calls.filter(
      (c) => c[0].type === "content_delta",
    );
    expect(deltas).toHaveLength(1);
    expect(deltas[0][0].payload).toEqual({ delta: "tok" });
  });

  it("start still generating → attach skips (no second pump)", async () => {
    const store = useConversationStore.getState();
    store.switchConversation(CID);
    // Simulate runSidecarTurn already owning the session.
    store.setGenerating(true, CID);
    setActiveSidecarTurn(CID, "root-1", "", "turn-start");

    const attach = vi.fn();
    stubSidecarApi({ attach });
    expect(await attachSidecarTurn(CID)).toBe(true);
    expect(attach).not.toHaveBeenCalled();
    expect(onEventCalls).toBe(0);
    expect(dispatchMock).not.toHaveBeenCalled();
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
