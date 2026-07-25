import { api } from "@/services/api";
import { getActiveSidecarTarget } from "@/services/sidecarRouting";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stopConversation } from "../stopTurn";

vi.mock("@/services/api", () => ({ api: { post: vi.fn() } }));
vi.mock("@/services/sidecarRouting", () => ({
  getActiveSidecarTarget: vi.fn(() => null),
}));

const post = vi.mocked(api.post);
const sidecarTarget = vi.mocked(getActiveSidecarTarget);

let cancelMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  post.mockReset();
  post.mockResolvedValue({ stopped: true });
  sidecarTarget.mockReset();
  sidecarTarget.mockReturnValue(null);
  cancelMock = vi.fn().mockResolvedValue(undefined);
  (globalThis as Record<string, unknown>).window = {
    sidecarApi: { cancel: cancelMock },
  };
});

describe("stopConversation", () => {
  it("cloud turn: POSTs /stop and returns stopped", async () => {
    await expect(stopConversation("conv-1")).resolves.toBe(true);
    expect(sidecarTarget).toHaveBeenCalledWith("conv-1");
    expect(cancelMock).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith("/v1/conversations/conv-1/stop");
  });

  it("cloud turn: propagates POST failures", async () => {
    post.mockRejectedValueOnce(new Error("boom"));
    await expect(stopConversation("conv-1")).rejects.toThrow("boom");
  });

  it("sidecar turn: routes to sidecarApi.cancel (never cloud POST)", async () => {
    sidecarTarget.mockReturnValue({
      rootId: "root-9",
      subpath: "scratch/c1",
      turnId: "turn-42",
    });

    await expect(stopConversation("conv-1")).resolves.toBe(true);

    expect(post).not.toHaveBeenCalled();
    expect(cancelMock).toHaveBeenCalledWith({
      rootId: "root-9",
      subpath: "scratch/c1",
      turnId: "turn-42",
      conversationId: "conv-1",
    });
  });

  it("sidecar turn: surfaces cancel failures for retry UI", async () => {
    sidecarTarget.mockReturnValue({
      rootId: "root-9",
      subpath: "",
      turnId: "turn-42",
    });
    cancelMock.mockRejectedValueOnce(new Error("本地引擎未运行，无法停止"));

    await expect(stopConversation("conv-1")).rejects.toThrow(/无法停止/);
    expect(post).not.toHaveBeenCalled();
  });

  it("sidecar turn without turnId: throws instead of silent no-op", async () => {
    sidecarTarget.mockReturnValue({ rootId: "root-9", subpath: "" });
    await expect(stopConversation("conv-1")).rejects.toThrow(/标识缺失/);
    expect(cancelMock).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
