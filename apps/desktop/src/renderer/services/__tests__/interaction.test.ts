import { api } from "@/services/api";
import { getActiveSidecarTarget } from "@/services/sidecarRouting";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resolveInteraction } from "../interaction";

vi.mock("@/services/api", () => ({ api: { post: vi.fn() } }));
vi.mock("@/services/sidecarRouting", () => ({
  getActiveSidecarTarget: vi.fn(() => null),
}));

const post = vi.mocked(api.post);
const sidecarTarget = vi.mocked(getActiveSidecarTarget);

let respondMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  post.mockReset();
  post.mockResolvedValue(undefined);
  sidecarTarget.mockReset();
  sidecarTarget.mockReturnValue(null);
  respondMock = vi.fn().mockResolvedValue({ resolved: true });
  (globalThis as Record<string, unknown>).window = {
    sidecarApi: { respond: respondMock },
  };
});

describe("resolveInteraction (统一 choke point)", () => {
  it("cloud turn: POSTs the kind body to the interactions endpoint", async () => {
    await resolveInteraction("conv-1", "ix-1", {
      kind: "approval",
      decision: "approve",
    });

    expect(sidecarTarget).toHaveBeenCalledWith("conv-1");
    expect(respondMock).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith(
      "/v1/conversations/conv-1/interactions/ix-1",
      { kind: "approval", decision: "approve" },
    );
  });

  it("cloud turn: routes escalate bodies the same way", async () => {
    await resolveInteraction("conv-1", "esc-1", {
      kind: "escalation",
      answer: "选 A",
      use_assumption: false,
      transfer_ownership: false,
    });
    expect(post).toHaveBeenCalledWith(
      "/v1/conversations/conv-1/interactions/esc-1",
      {
        kind: "escalation",
        answer: "选 A",
        use_assumption: false,
        transfer_ownership: false,
      },
    );
  });

  it("sidecar turn: forwards to sidecarApi.respond (never cloud POST)", async () => {
    sidecarTarget.mockReturnValue({ rootId: "root-9", subpath: "scratch/c1" });

    await resolveInteraction("conv-1", "ix-2", {
      kind: "approval",
      decision: "deny",
    });

    expect(post).not.toHaveBeenCalled();
    expect(respondMock).toHaveBeenCalledWith({
      rootId: "root-9",
      subpath: "scratch/c1",
      requestId: "ix-2",
      conversationId: "conv-1",
      result: { kind: "approval", decision: "deny" },
    });
  });

  it("sidecar turn: surfaces resolved:false so the card can retry", async () => {
    sidecarTarget.mockReturnValue({ rootId: "root-9", subpath: "" });
    respondMock.mockResolvedValueOnce({ resolved: false });

    await expect(
      resolveInteraction("conv-1", "esc-gone", {
        kind: "escalation",
        answer: "选 A",
        use_assumption: false,
        transfer_ownership: false,
      }),
    ).rejects.toThrow(/不存在或已处理/);
    expect(post).not.toHaveBeenCalled();
  });
});
