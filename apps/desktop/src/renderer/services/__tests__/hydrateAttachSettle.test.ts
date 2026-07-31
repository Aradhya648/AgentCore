/**
 * Hydrate attach/settle is independent of message-window adopt.
 *
 * Warm reopen (slice already has messages) must still enter settle/attach;
 * cold empty-slice adopt path must keep calling the same branches.
 */
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  attachOnOpen,
  settleCloudRunningAssistant,
  attachSidecarTurn,
  projectUnsyncedTurns,
} = vi.hoisted(() => ({
  attachOnOpen: vi.fn(async () => {}),
  settleCloudRunningAssistant: vi.fn(async () => "ghost" as const),
  attachSidecarTurn: vi.fn(async () => true),
  projectUnsyncedTurns: vi.fn(),
}));

vi.mock("../turns/recovery", () => ({
  attachOnOpen,
  settleCloudRunningAssistant,
}));

vi.mock("../turns/sidecarAttach", () => ({
  attachSidecarTurn,
}));

vi.mock("../turns/projectUnsynced", () => ({
  projectUnsyncedTurns,
}));

vi.mock("@/lib/log", () => ({
  logEvent: vi.fn(),
}));

import { runHydrateAttachSettle } from "../turns/hydrateAttachSettle";

const CID = "conv-hydrate-attach";

function seedMessages(
  last:
    | { role: "user" }
    | { role: "assistant"; status: "running" | "complete"; id?: string },
): void {
  const store = useConversationStore.getState();
  store.switchConversation(CID);
  store.addMessage(
    {
      id: "u1",
      role: "user",
      content: "q",
      createdAt: "2026-01-01T00:00:00Z",
      executionId: null,
      isStreaming: false,
    },
    CID,
  );
  if (last.role === "user") return;
  store.addMessage(
    {
      id: last.id ?? "a1",
      role: "assistant",
      content: last.status === "running" ? "partial" : "done",
      createdAt: "2026-01-01T00:00:01Z",
      executionId: null,
      isStreaming: last.status === "running",
      status: last.status,
      serverMessageId: last.id ?? "a1",
    },
    CID,
  );
}

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  attachOnOpen.mockClear();
  settleCloudRunningAssistant.mockClear();
  attachSidecarTurn.mockClear();
  projectUnsyncedTurns.mockClear();
  vi.stubGlobal("window", { __WEB__: true });
});

describe("runHydrateAttachSettle (warm reopen / cold adopt)", () => {
  it("warm reopen with running assistant still settles (messages.length>0)", async () => {
    seedMessages({ role: "assistant", status: "running" });
    expect(getRuntime(CID).messages.length).toBeGreaterThan(0);

    const branch = await runHydrateAttachSettle(CID, {
      sidecarLive: false,
      cloudLive: false,
      cloudKnown: true,
      pausedCount: 0,
      unsynced: [],
    });

    expect(branch).toBe("cloud");
    expect(settleCloudRunningAssistant).toHaveBeenCalledTimes(1);
    expect(settleCloudRunningAssistant).toHaveBeenCalledWith(
      CID,
      expect.objectContaining({
        cloudLive: false,
        cloudKnown: true,
        pausedCount: 0,
      }),
    );
    expect(attachOnOpen).not.toHaveBeenCalled();
    expect(attachSidecarTurn).not.toHaveBeenCalled();
  });

  it("warm reopen with last user + cloudLive attaches", async () => {
    seedMessages({ role: "user" });
    expect(getRuntime(CID).messages.at(-1)?.role).toBe("user");

    const branch = await runHydrateAttachSettle(CID, {
      sidecarLive: false,
      cloudLive: true,
      cloudKnown: true,
      pausedCount: 0,
      unsynced: [],
    });

    expect(branch).toBe("cloud");
    expect(attachOnOpen).toHaveBeenCalledTimes(1);
    expect(attachOnOpen).toHaveBeenCalledWith(CID);
    expect(settleCloudRunningAssistant).not.toHaveBeenCalled();
  });

  it("cold-style local sidecarLive still attaches (adopt-success path parity)", async () => {
    // Empty slice mirrors post-adopt readiness; branch must still attach.
    useConversationStore.getState().switchConversation(CID);
    expect(getRuntime(CID).messages.length).toBe(0);

    const ac = new AbortController();
    const branch = await runHydrateAttachSettle(
      CID,
      {
        sidecarLive: true,
        cloudLive: false,
        cloudKnown: true,
        pausedCount: 0,
        unsynced: [],
      },
      { signal: ac.signal },
    );

    expect(branch).toBe("local");
    expect(projectUnsyncedTurns).toHaveBeenCalledTimes(1);
    expect(attachSidecarTurn).toHaveBeenCalledTimes(1);
    expect(attachSidecarTurn).toHaveBeenCalledWith(CID, {
      signal: ac.signal,
    });
    expect(attachOnOpen).not.toHaveBeenCalled();
    expect(settleCloudRunningAssistant).not.toHaveBeenCalled();
  });

  it("cloud complete assistant does not attach or settle", async () => {
    seedMessages({ role: "assistant", status: "complete" });

    await runHydrateAttachSettle(CID, {
      sidecarLive: false,
      cloudLive: true,
      cloudKnown: true,
      pausedCount: 0,
      unsynced: [],
    });

    expect(attachOnOpen).not.toHaveBeenCalled();
    expect(settleCloudRunningAssistant).not.toHaveBeenCalled();
  });

  it("prefers runtime tail over a stale window (warm memory newer)", async () => {
    // Memory already has running assistant; a stale fetched window would have
    // ended on user — settle must follow runtime, not the window.
    seedMessages({ role: "assistant", status: "running" });
    expect(getRuntime(CID).messages.at(-1)?.role).toBe("assistant");

    await runHydrateAttachSettle(CID, {
      sidecarLive: false,
      cloudLive: false,
      cloudKnown: true,
      pausedCount: 0,
      unsynced: [],
    });

    expect(settleCloudRunningAssistant).toHaveBeenCalledTimes(1);
    expect(attachOnOpen).not.toHaveBeenCalled();
  });

  it("skips settle/attach when session abort already pumping", async () => {
    seedMessages({ role: "assistant", status: "running" });
    useConversationStore.getState().setGenerating(true, CID);
    useConversationStore.getState().setAbort(new AbortController(), CID);

    await runHydrateAttachSettle(CID, {
      sidecarLive: false,
      cloudLive: true,
      cloudKnown: true,
      pausedCount: 0,
      unsynced: [],
    });

    expect(settleCloudRunningAssistant).not.toHaveBeenCalled();
    expect(attachOnOpen).not.toHaveBeenCalled();
    expect(attachSidecarTurn).not.toHaveBeenCalled();
  });

  it("cold overlay isGenerating without abort still settles", async () => {
    // Mirrors adoptMessageWindow → shouldSetGeneratingOnHydrate: spinner on,
    // abort still null until attach/settle claims it.
    seedMessages({ role: "assistant", status: "running" });
    useConversationStore.getState().setGenerating(true, CID);
    expect(getRuntime(CID).abort).toBeNull();

    await runHydrateAttachSettle(CID, {
      sidecarLive: false,
      cloudLive: false,
      cloudKnown: true,
      pausedCount: 0,
      unsynced: [],
    });

    expect(settleCloudRunningAssistant).toHaveBeenCalledTimes(1);
  });
});
