import { fetchRunLlmWindow } from "@/services/llmWindow";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  api: { get: vi.fn() },
}));

const { api } = await import("@/services/api");

describe("fetchRunLlmWindow", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("calls the run-scoped llm-window endpoint", async () => {
    vi.mocked(api.get).mockResolvedValue({
      run_id: "cap",
      available: true,
      messages: [{ role: "system", content: "SYS" }],
    });
    const result = await fetchRunLlmWindow("conv-1", "msg-1", "cap");
    expect(api.get).toHaveBeenCalledWith(
      "/v1/conversations/conv-1/messages/msg-1/runs/cap/llm-window",
    );
    expect(result.available).toBe(true);
    expect(result.messages).toHaveLength(1);
  });
});
