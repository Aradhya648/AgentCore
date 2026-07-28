import { StreamError } from "@/lib/errors";
import type { OutboxFlushTurnResult } from "@shared/outbox-contract";
import type { SidecarTurnResult } from "@shared/sidecar-contract";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Resume reuses the普通本地回合 scaffolding; mock the heavy collaborators so the
// resume link's observable contract is asserted in isolation: the `resume` RPC
// params, event forwarding/filtering, outbox flush keyed on the *original* user
// bubble id (pinned on pause write-back), and the failure→StreamError("sidecar") /
// abort→AbortError mapping. The real conversation store is used (seeded below) so
// the optimistic-id reconcile is faithful.
vi.mock("@/services/streamConversation", () => ({
  dispatchSSEEvent: vi.fn(),
  flushPendingContent: vi.fn(),
  flushPendingFrames: vi.fn(),
}));
vi.mock("@/services/sidecarRouting", () => ({
  setActiveSidecarTurn: vi.fn(),
  clearActiveSidecarTurn: vi.fn(),
}));
vi.mock("@/services/sidecarStatus", () => ({
  takeRecentSidecarFailure: vi.fn(() => null),
}));
vi.mock("@/hooks/useConversations", () => ({
  patchConversationCache: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({
  notifyWarning: vi.fn(),
  notifySuccess: vi.fn(),
}));
// Deterministically control whether a cloud-proxy token is mintable: null ⇒ the turn
// falls back to the sidecar's local platform model (the divergence the badge/warning
// exist for); an object ⇒ a normal account-model turn. (The real resolver would attempt
// a live token mint, which has no server in the unit env.)
vi.mock("@/services/inferenceToken", () => ({
  resolveSidecarInference: vi.fn(),
}));

import { notifyWarning } from "@/lib/toast";
import { resolveSidecarInference } from "@/services/inferenceToken";
import { resetSidecarEventPumpForTests } from "../sidecarEventPump";
import { takeRecentSidecarFailure } from "@/services/sidecarStatus";
import { dispatchSSEEvent } from "@/services/streamConversation";
import { useConversationStore } from "@/stores/conversation";
import { useTurnModelStore } from "@/stores/turnModel";
import { resumeConversationViaSidecar } from "../streamConversationViaSidecar";

const dispatchSSEEventMock = vi.mocked(dispatchSSEEvent);
const takeRecentSidecarFailureMock = vi.mocked(takeRecentSidecarFailure);
const resolveSidecarInferenceMock = vi.mocked(resolveSidecarInference);
const notifyWarningMock = vi.mocked(notifyWarning);

type EventPush = { conversationId: string; turnId: string; event: unknown };

function turnResult(): SidecarTurnResult {
  return {
    turnId: "m-asst",
    messageId: "m-asst",
    content: "续答完成",
    reasoningContent: null,
    finishReason: "stop",
    model: "deepseek-v4-flash",
    rounds: 1,
    usage: {
      inputTokens: 10,
      outputTokens: 5,
      reasoningTokens: 0,
      cacheHitTokens: 0,
      cacheMissTokens: 0,
    },
    citations: [],
    runs: null,
    error: null,
  };
}

const baseRequest = {
  conversationId: "c1",
  rootId: "r1",
  messageId: "m-asst",
  decision: "continue" as const,
  note: "",
  selected: [],
  userMessage: "原始问题",
  userMessageId: "u-orig",
};

let onEventCb: ((push: EventPush) => void) | null;
let resumeMock: ReturnType<typeof vi.fn>;
let cancelMock: ReturnType<typeof vi.fn>;
let flushTurnMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetSidecarEventPumpForTests();
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  useTurnModelStore.setState({ byConversation: {} });
  dispatchSSEEventMock.mockReset();
  notifyWarningMock.mockReset();
  takeRecentSidecarFailureMock.mockReturnValue(null);
  // Default: no token mintable → the fallback path (what most existing cases assert with
  // `inference: undefined`). Cases that need a normal turn override this per-test.
  resolveSidecarInferenceMock.mockResolvedValue(null);

  onEventCb = null;
  resumeMock = vi.fn();
  cancelMock = vi.fn(() => Promise.resolve());
  flushTurnMock = vi.fn(
    async (): Promise<OutboxFlushTurnResult> => ({
      ok: true,
      synced: {
        conversationId: "c1",
        userMessageId: "u-orig",
        cloudUserMessageId: "real-uid",
        assistantMessageId: "m-asst",
        title: "续跑标题",
      },
    }),
  );

  // The SUT bridges to the main process via the preload `window.sidecarApi` /
  // `window.outboxApi`; the node test env has no `window`, so define them directly.
  (globalThis as Record<string, unknown>).window = {
    sidecarApi: {
      onEvent: vi.fn((cb: (push: EventPush) => void) => {
        onEventCb = cb;
        return () => {
          if (onEventCb === cb) onEventCb = null;
        };
      }),
      cancel: cancelMock,
      resume: resumeMock,
      startTurn: vi.fn(),
      respond: vi.fn(),
    },
    outboxApi: {
      flushTurn: flushTurnMock,
      flush: vi.fn(),
      status: vi.fn(async () => ({ pending: [] })),
      onSynced: vi.fn(() => () => {}),
      authRefresh: vi.fn(async () => "auth_dead" as const),
    },
  };
});

afterEach(() => {
  resetSidecarEventPumpForTests();
  (globalThis as Record<string, unknown>).window = undefined;
});

/** Seed the user bubble that was pinned on pause write-back (same id end-to-end). */
function seedOriginalUserBubble(
  conversationId: string,
  userMessageId: string,
  content: string,
): void {
  useConversationStore.getState().addMessage(
    {
      id: userMessageId,
      role: "user",
      content,
      createdAt: "",
      executionId: null,
      isStreaming: false,
    },
    conversationId,
  );
}

describe("resumeConversationViaSidecar", () => {
  it("drives the resume RPC, forwards only this conversation's events, and reconciles the original user bubble on outbox sync", async () => {
    seedOriginalUserBubble("c1", "u-orig", "原始问题");

    const result = turnResult();
    // `resume` runs once the SUT reaches `await invoke()` — by then onEvent is
    // subscribed, so the engine "streams" one matching + one foreign event.
    resumeMock.mockImplementation(async () => {
      onEventCb?.({
        conversationId: "c1",
        turnId: "m-asst",
        event: { type: "content_delta", payload: { delta: "x" } },
      });
      onEventCb?.({
        conversationId: "other",
        turnId: "m-asst",
        event: { type: "content_delta", payload: { delta: "y" } },
      });
      return result;
    });

    await expect(resumeConversationViaSidecar(baseRequest)).resolves.toBe(
      result,
    );

    expect(resumeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        rootId: "r1",
        conversationId: "c1",
        messageId: "m-asst",
        decision: "continue",
        note: "",
        selected: [],
        subpath: undefined,
        inference: undefined,
        traceId: expect.any(String),
      }),
    );
    // Foreign-conversation event filtered out; only c1's reached the dispatcher.
    expect(dispatchSSEEventMock).toHaveBeenCalledTimes(1);

    // Outbox flush is keyed on the original user bubble id (pause write-back).
    expect(flushTurnMock).toHaveBeenCalledWith({ userMessageId: "u-orig" });

    // The original bubble's id is swapped for the authoritative one when unchanged.
    const userMsg = useConversationStore
      .getState()
      .byId.c1?.messages.find((m) => m.role === "user");
    expect(userMsg?.id).toBe("real-uid");
  });

  it("records the turn's real model and warns (naming it) when it fell back to the local platform model (no token)", async () => {
    resolveSidecarInferenceMock.mockResolvedValue(null); // no token → platform fallback
    flushTurnMock.mockResolvedValue({
      ok: true,
      synced: {
        conversationId: "c1",
        userMessageId: "u-orig",
        cloudUserMessageId: "real-uid",
        assistantMessageId: null,
        title: null,
      },
    });
    seedOriginalUserBubble("c1", "u-orig", "原始问题");
    // The sidecar reports the model it actually ran on — here the local platform model.
    resumeMock.mockResolvedValue({ ...turnResult(), model: "gpt-4o" });

    await resumeConversationViaSidecar(baseRequest);

    // The badge store now knows this conversation's last turn actually ran on gpt-4o.
    expect(useTurnModelStore.getState().byConversation.c1).toBe("gpt-4o");
    // Non-blocking heads-up was raised, naming the fallback model.
    expect(notifyWarningMock).toHaveBeenCalledTimes(1);
    expect(notifyWarningMock.mock.calls[0]?.[1]?.description).toContain(
      "gpt-4o",
    );
  });

  it("records the account model and does NOT warn on a normal turn (token present)", async () => {
    resolveSidecarInferenceMock.mockResolvedValue({
      baseUrl: "https://x/v1/inference/v1",
      apiKey: "tok",
      model: "deepseek-v4-flash",
    });
    flushTurnMock.mockResolvedValue({
      ok: true,
      synced: {
        conversationId: "c1",
        userMessageId: "u-orig",
        cloudUserMessageId: "real-uid",
        assistantMessageId: null,
        title: null,
      },
    });
    seedOriginalUserBubble("c1", "u-orig", "原始问题");
    resumeMock.mockResolvedValue({
      ...turnResult(),
      model: "deepseek-v4-flash",
    });

    await resumeConversationViaSidecar(baseRequest);

    // A token was present, so the resume carried it and no fallback warning was raised.
    expect(resumeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        inference: expect.objectContaining({ model: "deepseek-v4-flash" }),
      }),
    );
    expect(useTurnModelStore.getState().byConversation.c1).toBe(
      "deepseek-v4-flash",
    );
    expect(notifyWarningMock).not.toHaveBeenCalled();
  });

  it("keeps synced_pending when outbox flush is still pending", async () => {
    // Token present so platform-fallback warning does not fire — we only assert
    // the writeback path leaves synced_pending without a sync-retry toast.
    resolveSidecarInferenceMock.mockResolvedValue({
      baseUrl: "https://x/v1/inference/v1",
      apiKey: "tok",
      model: "deepseek-v4-flash",
    });
    flushTurnMock.mockResolvedValue({
      ok: false,
      error: "writeback_pending",
    });
    seedOriginalUserBubble("c1", "u-orig", "原始问题");
    resumeMock.mockResolvedValue(turnResult());

    await resumeConversationViaSidecar(baseRequest);

    const userMsg = useConversationStore
      .getState()
      .byId.c1?.messages.find((m) => m.role === "user");
    expect(userMsg?.syncStatus).toBe("synced_pending");
    // No toast / manual-retry path (as-built: 双模式工作区 §10.3; 前端 UX §一B).
    expect(notifyWarningMock).not.toHaveBeenCalled();
  });

  it("maps a resume failure to a sidecar StreamError carrying the engine's reason", async () => {
    resumeMock.mockRejectedValue(new Error("引擎崩了"));

    const err = await resumeConversationViaSidecar(baseRequest).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(StreamError);
    expect((err as StreamError).kind).toBe("sidecar");
    expect((err as StreamError).serverMessage).toContain("引擎崩了");
    // A turn that never completed must not flush outbox.
    expect(flushTurnMock).not.toHaveBeenCalled();
  });

  it("surfaces IPC invalid-args rejects with field-level sidecar banner copy", async () => {
    // Electron wraps main-process throws; message after unwrap matches IpcInvalidArgsError.
    resumeMock.mockRejectedValue(
      new Error(
        "Error invoking remote method 'sidecar:resume': Error: 无效的 IPC 入参：sidecar:resume（字段 permissionAxes 期望 string）",
      ),
    );

    const err = await resumeConversationViaSidecar(baseRequest).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(StreamError);
    expect((err as StreamError).kind).toBe("sidecar");
    expect((err as StreamError).serverMessage).toBe(
      "本地引擎出错：请求参数校验失败（permissionAxes 期望 string，sidecar:resume）",
    );
  });

  it("prefers an onStatus lifecycle diagnostic over the rejection reason", async () => {
    takeRecentSidecarFailureMock.mockReturnValue(
      "找不到 Python，无法启动本地引擎",
    );
    resumeMock.mockRejectedValue(new Error("generic rpc error"));

    const err = await resumeConversationViaSidecar(baseRequest).catch(
      (e: unknown) => e,
    );
    expect((err as StreamError).serverMessage).toBe(
      "找不到 Python，无法启动本地引擎",
    );
  });

  it("does not invoke when signal is already aborted (H1 pre-aborted gate)", async () => {
    const ac = new AbortController();
    ac.abort();
    const err = await resumeConversationViaSidecar({
      ...baseRequest,
      signal: ac.signal,
    }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DOMException);
    expect((err as DOMException).name).toBe("AbortError");
    expect(resumeMock).not.toHaveBeenCalled();
    expect(cancelMock).not.toHaveBeenCalled();
  });

  it("surfaces a user stop as AbortError and cancels the engine", async () => {
    const ac = new AbortController();
    let rejectResume: (e: unknown) => void = () => {};
    resumeMock.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectResume = reject;
        }),
    );

    const p = resumeConversationViaSidecar({
      ...baseRequest,
      signal: ac.signal,
    });
    p.catch(() => {});

    // `resume` is invoked only after the abort listener is registered, so waiting
    // for it guarantees the stop button is wired before we press it.
    await vi.waitFor(() => expect(resumeMock).toHaveBeenCalled());
    ac.abort();
    expect(cancelMock).toHaveBeenCalledWith(
      expect.objectContaining({ rootId: "r1", turnId: "m-asst" }),
    );

    // The cancelled RPC then rejects; the abort wins → AbortError, no error banner.
    rejectResume(new Error("turn cancelled"));
    const err = await p.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DOMException);
    expect((err as DOMException).name).toBe("AbortError");
    expect(flushTurnMock).not.toHaveBeenCalled();
  });

  it("maps honest stop (phase stopping, signal intact) to AbortError", async () => {
    // Production stopGeneration does NOT abort AbortSignal — it sets turnPhase
    // stopping and sidecar cancel; startTurn/resume then reject with turn cancelled.
    seedOriginalUserBubble("c1", "u-orig", "原始问题");

    let rejectResume: (e: unknown) => void = () => {};
    resumeMock.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectResume = reject;
        }),
    );

    const ac = new AbortController();
    const p = resumeConversationViaSidecar({
      ...baseRequest,
      signal: ac.signal,
    });
    p.catch(() => {});

    await vi.waitFor(() => expect(resumeMock).toHaveBeenCalled());
    // Honest stop mid-flight: phase → stopping, signal stays live.
    useConversationStore.getState().setTurnPhase("stopping", "c1");
    expect(ac.signal.aborted).toBe(false);
    rejectResume(
      new Error(
        "Error invoking remote method 'sidecar:resume': Error: turn cancelled",
      ),
    );

    const err = await p.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DOMException);
    expect((err as DOMException).name).toBe("AbortError");
    expect(flushTurnMock).not.toHaveBeenCalled();
  });

  it("maps turn-cancelled reject to AbortError even after message_end left phase stopped", async () => {
    // FIFO: message_end(cancelled) → completeTurnPhase(stopped) before RPC reject.
    seedOriginalUserBubble("c1", "u-orig", "原始问题");

    let rejectResume: (e: unknown) => void = () => {};
    resumeMock.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectResume = reject;
        }),
    );

    const p = resumeConversationViaSidecar(baseRequest);
    p.catch(() => {});

    await vi.waitFor(() => expect(resumeMock).toHaveBeenCalled());
    useConversationStore.getState().setTurnPhase("stopped", "c1");
    rejectResume(new Error("turn cancelled"));

    const err = await p.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DOMException);
    expect((err as DOMException).name).toBe("AbortError");
    expect(flushTurnMock).not.toHaveBeenCalled();
  });
});
