import { ApiError } from "@/services/api";
import { resolveInteraction } from "@/services/interaction";
import { runResume } from "@/services/turns";
import { useInteractionStore } from "@/stores/interactions";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  isInteractionOrphanedError,
  isPendingInteractionsAwaitingError,
  submitInteraction,
} from "../interactionSubmit";

vi.mock("@/services/interaction", () => ({
  resolveInteraction: vi.fn(),
}));
vi.mock("@/services/turns", () => ({
  runResume: vi.fn(),
}));
vi.mock("@/stores/composer", () => ({
  useComposerDraftStore: {
    getState: () => ({ fill: vi.fn() }),
  },
}));

const resolveMock = vi.mocked(resolveInteraction);
const resumeMock = vi.mocked(runResume);
const store = () => useInteractionStore.getState();

beforeEach(() => {
  store().clear();
  resolveMock.mockReset();
  resumeMock.mockReset();
  resolveMock.mockResolvedValue(undefined);
  resumeMock.mockResolvedValue(undefined);
});

describe("submitInteraction path table", () => {
  it("hot path: approval → resolveInteraction + resolved", async () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "x", arguments: {} },
    });
    const result = await submitInteraction({
      id: "a1",
      kind: "approval",
      conversationId: "c1",
      hotBody: { kind: "approval", decision: "approve" },
    });
    expect(result).toBe("ok");
    expect(resolveMock).toHaveBeenCalledWith("c1", "a1", {
      kind: "approval",
      decision: "approve",
    });
    expect(store().get("a1")?.status).toBe("resolved");
  });

  it("cold path: ask_user → runResume", async () => {
    store().upsertRequired({
      kind: "ask_user",
      conversationId: "c1",
      messageId: "m1",
      payload: { checkpoint_id: "cp1", question: "q" },
    });
    const result = await submitInteraction({
      id: "cp1",
      kind: "ask_user",
      conversationId: "c1",
      cold: { messageId: "srv-m1", decision: "continue", note: "" },
    });
    expect(result).toBe("ok");
    expect(resumeMock).toHaveBeenCalledWith(
      "srv-m1",
      "continue",
      "",
      undefined,
      undefined,
      undefined,
    );
    expect(store().get("cp1")?.status).toBe("resolved");
  });

  it("cold path after recovery: no interactions entry still calls runResume (team_preview)", async () => {
    // Recovery clears cold pending_interactions; pausedTurns is the authority.
    expect(store().get("tp1")).toBeUndefined();
    const result = await submitInteraction({
      id: "tp1",
      kind: "team_preview",
      conversationId: "c1",
      cold: {
        messageId: "srv-m1",
        decision: "continue",
        note: "先做公开竞品",
      },
    });
    expect(result).toBe("ok");
    expect(resumeMock).toHaveBeenCalledWith(
      "srv-m1",
      "continue",
      "先做公开竞品",
      undefined,
      undefined,
      undefined,
    );
    expect(store().get("tp1")?.status).toBe("resolved");
  });

  it("cold path after recovery: ask_user without interactions entry still resumes", async () => {
    expect(store().get("cp-ask")).toBeUndefined();
    const result = await submitInteraction({
      id: "cp-ask",
      kind: "ask_user",
      conversationId: "c1",
      cold: {
        messageId: "srv-ask",
        decision: "continue",
        note: "选 A",
        selected: ["a"],
      },
    });
    expect(result).toBe("ok");
    expect(resumeMock).toHaveBeenCalledWith(
      "srv-ask",
      "continue",
      "选 A",
      ["a"],
      undefined,
      undefined,
    );
  });

  it("cold path: runResume failure does not markResolved", async () => {
    resumeMock.mockRejectedValue(
      new Error("resume blocked: sidecar unavailable"),
    );
    await expect(
      submitInteraction({
        id: "tp1",
        kind: "team_preview",
        conversationId: "c1",
        cold: { messageId: "srv-m1", decision: "continue", note: "" },
      }),
    ).rejects.toThrow(/sidecar unavailable/);
    // Stub from markResolved must not appear — failure left no resolved entry,
    // or if a prior pending existed it would reopen. Here there was none.
    expect(store().get("tp1")).toBeUndefined();
  });

  it("cold path: tracked entry reopens on runResume failure (no fake resolved)", async () => {
    store().upsertRequired({
      kind: "plan_review",
      conversationId: "c1",
      messageId: "m1",
      payload: { checkpoint_id: "pr1", steps: [], pending: [] },
    });
    resumeMock.mockRejectedValue(
      new Error("resume blocked: sidecar probe failed"),
    );
    await expect(
      submitInteraction({
        id: "pr1",
        kind: "plan_review",
        conversationId: "c1",
        cold: { messageId: "srv-pr", decision: "continue", note: "" },
      }),
    ).rejects.toThrow(/probe failed/);
    expect(store().get("pr1")?.status).toBe("pending");
  });

  it("410 interaction_orphaned → orphaned status (no reopen)", async () => {
    store().upsertRequired({
      kind: "escalation",
      conversationId: "c1",
      messageId: "m1",
      payload: { escalation_id: "e1", question: "q", assumption: "a" },
    });
    resolveMock.mockRejectedValue(
      new ApiError(
        410,
        JSON.stringify({ detail: { code: "interaction_orphaned" } }),
      ),
    );
    const result = await submitInteraction({
      id: "e1",
      kind: "escalation",
      conversationId: "c1",
      hotBody: {
        kind: "escalation",
        answer: "",
        use_assumption: true,
        transfer_ownership: false,
      },
    });
    expect(result).toBe("orphaned");
    expect(store().get("e1")?.status).toBe("orphaned");
  });

  it("non-410 failure → reopen for retry", async () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "x", arguments: {} },
    });
    resolveMock.mockRejectedValue(new ApiError(500, "boom"));
    await expect(
      submitInteraction({
        id: "a1",
        kind: "approval",
        conversationId: "c1",
        hotBody: { kind: "approval", decision: "deny" },
      }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(store().get("a1")?.status).toBe("pending");
  });

  it("hot submitting guard blocks double submit", async () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "x", arguments: {} },
    });
    let release!: () => void;
    resolveMock.mockImplementation(
      () =>
        new Promise((r) => {
          release = () => r(undefined);
        }),
    );
    const first = submitInteraction({
      id: "a1",
      kind: "approval",
      conversationId: "c1",
      hotBody: { kind: "approval", decision: "approve" },
    });
    const second = await submitInteraction({
      id: "a1",
      kind: "approval",
      conversationId: "c1",
      hotBody: { kind: "approval", decision: "approve" },
    });
    expect(second).toBe("busy");
    release();
    await first;
  });

  it("cold path does not return busy when interactions entry is absent", async () => {
    // While a cold submit is in flight, a second call must NOT get "busy"
    // (dedup is the caller's local submitting state, not interactions.beginSubmit).
    let resolveFirst!: () => void;
    const firstGate = new Promise<void>((r) => {
      resolveFirst = () => r();
    });
    resumeMock.mockImplementationOnce(() => firstGate);
    resumeMock.mockResolvedValueOnce(undefined);

    const first = submitInteraction({
      id: "tp1",
      kind: "team_preview",
      conversationId: "c1",
      cold: { messageId: "srv-m1", decision: "continue", note: "" },
    });
    const second = await submitInteraction({
      id: "tp1",
      kind: "team_preview",
      conversationId: "c1",
      cold: { messageId: "srv-m1", decision: "continue", note: "" },
    });
    expect(second).toBe("ok");
    expect(resumeMock).toHaveBeenCalledTimes(2);
    resolveFirst();
    await expect(first).resolves.toBe("ok");
  });
});

describe("error helpers", () => {
  it("detects 410 orphaned from detail.code", () => {
    const err = new ApiError(
      410,
      JSON.stringify({ detail: { code: "interaction_orphaned" } }),
    );
    expect(isInteractionOrphanedError(err)).toBe(true);
  });

  it("detects 409 pending_interactions_awaiting", () => {
    const err = new ApiError(
      409,
      JSON.stringify({
        detail: {
          code: "pending_interactions_awaiting",
          pending_kinds: ["approval"],
        },
      }),
    );
    expect(isPendingInteractionsAwaitingError(err)).toBe(true);
  });
});
