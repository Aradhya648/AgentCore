import { api } from "@/services/api";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSimulationRun } from "../api";

vi.mock("@/services/api", () => ({ api: { post: vi.fn() } }));

const post = vi.mocked(api.post);

beforeEach(() => {
  post.mockReset();
});

describe("createSimulationRun", () => {
  it("defaults scripted:true (aligns with Unity; no real LLM)", async () => {
    post.mockResolvedValue({
      id: "run-1",
      scenario: "town",
      current_tick: 0,
      status: "created",
    });

    const view = await createSimulationRun({ scenario: "town" });

    expect(post).toHaveBeenCalledWith("/v1/simulation/runs", {
      scenario: "town",
      seed: undefined,
      scripted: true,
    });
    expect(view).toEqual({
      id: "run-1",
      scenario: "town",
      tick: 0,
      hour: 0,
      status: "created",
    });
  });

  it("allows explicit scripted:false override", async () => {
    post.mockResolvedValue({
      id: "run-2",
      scenario: "town",
      current_tick: 0,
      status: "created",
    });

    await createSimulationRun({ scenario: "town", scripted: false });

    expect(post).toHaveBeenCalledWith("/v1/simulation/runs", {
      scenario: "town",
      seed: undefined,
      scripted: false,
    });
  });
});
