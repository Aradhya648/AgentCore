import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();

vi.mock("@/api/client", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

import { cancelQueuedTurn, stopConversation } from "../turn";

describe("stopConversation", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("POST /stop 成功 → 返回 stopped", async () => {
    apiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ stopped: true }),
    });
    await expect(stopConversation("c1")).resolves.toBe(true);
    expect(apiFetch).toHaveBeenCalledWith("/v1/conversations/c1/stop", {
      method: "POST",
    });
  });

  it("HTTP 非 2xx → 抛错（供 UI 可见重试，不再静默）", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 503 });
    await expect(stopConversation("c1")).rejects.toThrow(/停止失败/);
  });

  it("网络失败 → 抛错", async () => {
    apiFetch.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(stopConversation("c1")).rejects.toThrow();
  });
});

describe("cancelQueuedTurn", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("成功 → cancelled", async () => {
    apiFetch.mockResolvedValue({ ok: true, status: 200 });
    await expect(cancelQueuedTurn("c1", "q1")).resolves.toBe("cancelled");
    expect(apiFetch).toHaveBeenCalledWith(
      "/v1/conversations/c1/queued-turns/q1/cancel",
      { method: "POST" },
    );
  });

  it("404 → gone（调用方本地清轻态，不抛）", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 404 });
    await expect(cancelQueuedTurn("c1", "q1")).resolves.toBe("gone");
  });

  it("其它非 2xx → 抛错", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 503 });
    await expect(cancelQueuedTurn("c1", "q1")).rejects.toThrow(/取消排队失败/);
  });
});
