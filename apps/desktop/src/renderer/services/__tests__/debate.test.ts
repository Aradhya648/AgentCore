import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  api: { post: vi.fn() },
}));

vi.mock("@/services/sidecarRouting", () => ({
  getActiveSidecarTarget: vi.fn(() => null),
}));

import { api } from "@/services/api";
import { submitDebateSteer } from "../debate";

const post = vi.mocked(api.post);

describe("submitDebateSteer", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ ok: true, queued: 1 });
  });

  it("posts continue with focus/ask to debate-steer", async () => {
    await submitDebateSteer("conv-1", {
      executionId: "exec-1",
      decision: {
        kind: "continue",
        focus: "定价",
        ask: "谁兜底？",
        askTarget: "pro",
      },
    });
    expect(post).toHaveBeenCalledWith("/v1/conversations/conv-1/debate-steer", {
      execution_id: "exec-1",
      decision: "continue",
      focus: "定价",
      ask: "谁兜底？",
      ask_target: "pro",
    });
  });

  it("posts conclude without focus", async () => {
    await submitDebateSteer("conv-1", {
      executionId: "exec-1",
      decision: { kind: "conclude", ask: "", askTarget: "" },
    });
    expect(post).toHaveBeenCalledWith("/v1/conversations/conv-1/debate-steer", {
      execution_id: "exec-1",
      decision: "conclude",
      focus: "",
      ask: "",
      ask_target: "",
    });
  });
});
