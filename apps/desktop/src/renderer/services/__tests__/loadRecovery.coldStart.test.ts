/**
 * Cold-start hydrate regression (D7 二次修订).
 *
 * First acceptance failed because recovery branched on `resolveSidecarRoot`
 * (React Query conversation-list cache — empty after refresh). These tests
 * deliberately do NOT prefill conversation/workspace query caches and do NOT
 * mock resolveSidecarRoot: local recovery must fire from main-process facts alone.
 */
import { usePausedTurnStore } from "@/stores/pausedTurns";
import type { SidecarUnsyncedTurnSummary } from "@shared/sidecar-contract";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();

vi.mock("@/services/api", () => ({
  api: { get: (...args: unknown[]) => apiGet(...args) },
}));

vi.mock("@/services/sidecarRouting", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/sidecarRouting")>();
  return {
    ...actual,
    // If hydrate/loadRecovery still calls this for branch selection, fail loud.
    resolveSidecarRoot: vi.fn(async () => {
      throw new Error(
        "resolveSidecarRoot must not gate recovery (cold-start lesson)",
      );
    }),
  };
});

import { loadRecovery, shouldHydrateLocalRecovery } from "@/services/resume";

const CID = "conv-cold-start";

function unsyncedSummary(
  over: Partial<SidecarUnsyncedTurnSummary> = {},
): SidecarUnsyncedTurnSummary {
  return {
    user_message_id: "u1",
    user_message: "q",
    message_id: "a1",
    trace_id: "a".repeat(32),
    phase: "ready",
    updated_at: 1,
    content: "ans",
    reasoning_content: null,
    citations: [],
    runs: null,
    finish_reason: "stop",
    input_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    cache_hit_tokens: 0,
    cache_miss_tokens: 0,
    ...over,
  };
}

beforeEach(() => {
  usePausedTurnStore.getState().clear();
  apiGet.mockReset();
  vi.unstubAllGlobals();
});

describe("loadRecovery cold start (no React Query / no resolveSidecarRoot)", () => {
  it("reports sidecarLive from recovery IPC with empty conversation cache", async () => {
    const recoveryIpc = vi.fn(async () => ({
      liveRunning: true,
      turnId: "turn-1",
      unsynced: [],
      paused: [],
    }));
    apiGet.mockResolvedValue({
      live_running: false,
      paused: [],
      pending_interactions: [],
    });

    vi.stubGlobal("window", {
      __WEB__: false,
      sidecarApi: { recovery: recoveryIpc },
    });

    const r = await loadRecovery(CID);
    expect(recoveryIpc).toHaveBeenCalledWith({ conversationId: CID });
    expect(r.sidecarLive).toBe(true);
    expect(r.cloudLive).toBe(false);
    expect(r.turnId).toBe("turn-1");
    expect(shouldHydrateLocalRecovery(r)).toBe(true);
  });

  it("takes local hydrate path for unsynced-only (no live turn)", async () => {
    const recoveryIpc = vi.fn(async () => ({
      liveRunning: false,
      unsynced: [unsyncedSummary()],
      paused: [],
    }));
    apiGet.mockResolvedValue({
      live_running: false,
      paused: [],
      pending_interactions: [],
    });

    vi.stubGlobal("window", {
      __WEB__: false,
      sidecarApi: { recovery: recoveryIpc },
    });

    const r = await loadRecovery(CID);
    expect(r.sidecarLive).toBe(false);
    expect(r.unsynced).toHaveLength(1);
    expect(shouldHydrateLocalRecovery(r)).toBe(true);
  });

  it("merges paused frames and survives cloud failure", async () => {
    const recoveryIpc = vi.fn(async () => ({
      liveRunning: false,
      unsynced: [],
      paused: [
        {
          message_id: "m-pause",
          kind: "plan_review",
          checkpoint_id: "cp1",
          user_message: "q",
          steps: [],
          pending: [],
        },
      ],
    }));
    apiGet.mockRejectedValue(new Error("network down"));

    vi.stubGlobal("window", {
      __WEB__: false,
      sidecarApi: { recovery: recoveryIpc },
    });

    const r = await loadRecovery(CID);
    expect(r.pausedCount).toBe(1);
    expect(r.cloudLive).toBe(false);
    expect(usePausedTurnStore.getState().pending).toHaveLength(1);
    expect(usePausedTurnStore.getState().pending[0]?.origin).toBe("sidecar");
  });

  it("tags each mixed-frame with its own origin (not conversation-wide)", async () => {
    const recoveryIpc = vi.fn(async () => ({
      liveRunning: false,
      unsynced: [],
      paused: [
        {
          message_id: "m-local",
          kind: "ask_user",
          checkpoint_id: "cp-local",
          user_message: "local q",
          steps: [],
          pending: [],
        },
      ],
    }));
    apiGet.mockResolvedValue({
      live_running: false,
      paused: [
        {
          message_id: "m-cloud",
          kind: "plan_review",
          checkpoint_id: "cp-cloud",
          user_message: "cloud q",
          steps: [],
          pending: [],
        },
      ],
      pending_interactions: [],
    });

    vi.stubGlobal("window", {
      __WEB__: false,
      sidecarApi: { recovery: recoveryIpc },
    });

    const r = await loadRecovery(CID);
    expect(r.pausedCount).toBe(2);
    const byId = Object.fromEntries(
      usePausedTurnStore.getState().pending.map((p) => [p.messageId, p.origin]),
    );
    expect(byId["m-local"]).toBe("sidecar");
    expect(byId["m-cloud"]).toBe("server");
  });

  it("sidecar wins collision and keeps origin=sidecar", async () => {
    const recoveryIpc = vi.fn(async () => ({
      liveRunning: false,
      unsynced: [],
      paused: [
        {
          message_id: "m-same",
          kind: "ask_user",
          checkpoint_id: "cp-local",
          user_message: "from sidecar",
          steps: [],
          pending: [],
        },
      ],
    }));
    apiGet.mockResolvedValue({
      live_running: false,
      paused: [
        {
          message_id: "m-same",
          kind: "ask_user",
          checkpoint_id: "cp-cloud",
          user_message: "from cloud",
          steps: [],
          pending: [],
        },
      ],
      pending_interactions: [],
    });

    vi.stubGlobal("window", {
      __WEB__: false,
      sidecarApi: { recovery: recoveryIpc },
    });

    await loadRecovery(CID);
    const entries = usePausedTurnStore.getState().pending;
    expect(entries).toHaveLength(1);
    expect(entries[0]?.origin).toBe("sidecar");
    expect(entries[0]?.userMessage).toBe("from sidecar");
  });

  it("web path stays cloud-only (hasLocalEngine false)", async () => {
    apiGet.mockResolvedValue({
      live_running: true,
      paused: [],
      pending_interactions: [],
    });

    vi.stubGlobal("window", {
      __WEB__: true,
      sidecarApi: {
        recovery: vi.fn(async () => {
          throw new Error("must not call local recovery on web");
        }),
      },
    });

    const r = await loadRecovery(CID);
    expect(r.sidecarLive).toBe(false);
    expect(r.cloudLive).toBe(true);
    expect(shouldHydrateLocalRecovery(r)).toBe(false);
  });

  it("recovery snapshot carrying ceo_review hydrates it onto the resume frame", async () => {
    // REST schema 未列该字段；宽松读——后端带了就透传，absent → undefined。
    apiGet.mockResolvedValue({
      live_running: false,
      paused: [
        {
          message_id: "m-cr",
          kind: "plan_review",
          checkpoint_id: "cp-cr",
          user_message: "q",
          steps: [{ run_id: "r1", role: "调研", summary: "ok" }],
          pending: [],
          ceo_review: {
            conclusion: "可放行",
            risks: ["预算偏乐观"],
            suggestions: [],
          },
        },
        {
          message_id: "m-no-cr",
          kind: "plan_review",
          checkpoint_id: "cp-no-cr",
          user_message: "q2",
          steps: [],
          pending: [],
        },
      ],
      pending_interactions: [],
    });

    vi.stubGlobal("window", { __WEB__: true });

    await loadRecovery(CID);
    const entries = usePausedTurnStore.getState().pending;
    expect(entries).toHaveLength(2);
    const withReview = entries.find((e) => e.messageId === "m-cr");
    const without = entries.find((e) => e.messageId === "m-no-cr");
    expect(withReview?.ceoReview).toEqual({
      conclusion: "可放行",
      risks: ["预算偏乐观"],
      suggestions: [],
    });
    expect(without?.ceoReview).toBeUndefined();
  });

  it("empty recovery snapshot does not wipe non-empty live frames", async () => {
    // Live pause surfaced a card; stale/empty /recovery must not clear it.
    usePausedTurnStore.getState().addLiveResume({
      messageId: "m-live",
      conversationId: CID,
      checkpointId: "cp-live",
      kind: "ask_user",
      userMessage: "q",
      userMessageId: "u1",
      steps: [],
      pending: [],
      workers: [],
      tools: [],
      primitive: "delegate",
      motion: "",
      form: "",
      sides: [],
      maxRounds: 0,
      thorough: true,
      offerResearchFirst: false,
      researchFirstRecommended: false,
      question: "继续？",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [],
      intent: "decision",
      origin: "server",
    });

    apiGet.mockResolvedValue({
      live_running: false,
      paused: [],
      pending_interactions: [],
    });

    vi.stubGlobal("window", {
      __WEB__: true,
      sidecarApi: {
        recovery: vi.fn(async () => {
          throw new Error("must not call local recovery on web");
        }),
      },
    });

    const r = await loadRecovery(CID);
    expect(r.pausedCount).toBe(0);
    const pending = usePausedTurnStore.getState().pending;
    expect(pending).toHaveLength(1);
    expect(pending[0]?.messageId).toBe("m-live");
    expect(pending[0]?.checkpointId).toBe("cp-live");
  });
});

describe("shouldHydrateLocalRecovery", () => {
  it("is true for sidecar live / unsynced / paused", () => {
    expect(
      shouldHydrateLocalRecovery({
        sidecarLive: false,
        cloudLive: true,
        pausedCount: 0,
        unsynced: [],
      }),
    ).toBe(false);
    expect(
      shouldHydrateLocalRecovery({
        sidecarLive: true,
        cloudLive: false,
        pausedCount: 0,
        unsynced: [],
      }),
    ).toBe(true);
    expect(
      shouldHydrateLocalRecovery({
        sidecarLive: false,
        cloudLive: false,
        pausedCount: 1,
        unsynced: [],
      }),
    ).toBe(true);
  });
});
