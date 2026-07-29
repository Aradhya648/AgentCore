import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const resolveInteraction = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/interaction", () => ({
  resolveInteraction: (...args: unknown[]) => resolveInteraction(...args),
}));

import { ApiError } from "@/services/api";
import {
  fulfillClientToolOnce,
  resetClientToolFulfillmentForTests,
} from "../clientToolFulfill";

describe("fulfillClientToolOnce (request_id 在飞/成功去重)", () => {
  beforeEach(() => {
    resetClientToolFulfillmentForTests();
    resolveInteraction.mockReset();
    resolveInteraction.mockResolvedValue(undefined);
  });
  afterEach(() => resetClientToolFulfillmentForTests());

  it("runs perform once and resolves with the result", async () => {
    const perform = vi.fn().mockResolvedValue({ ok: true, value: { x: 1 } });

    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });

    expect(perform).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledWith("c1", "r1", {
      kind: "client_tool",
      ok: true,
      value: { x: 1 },
    });
  });

  it("skips side effect on a second call with the same request_id after success", async () => {
    const perform = vi.fn().mockResolvedValue({ ok: true, value: "done" });

    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });
    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });

    expect(perform).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledTimes(1);
  });

  it("joins in-flight perform so a concurrent redelivery does not double-run", async () => {
    let release!: (v: { ok: true; value: string }) => void;
    const perform = vi.fn(
      () =>
        new Promise<{ ok: true; value: string }>((r) => {
          release = r;
        }),
    );

    const a = fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });
    const b = fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });

    expect(perform).toHaveBeenCalledTimes(1);
    release({ ok: true, value: "once" });
    await Promise.all([a, b]);

    expect(perform).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledTimes(1);
  });

  it("retries resolve (not perform) when first settle failed and side effect succeeded", async () => {
    const perform = vi.fn().mockResolvedValue({ ok: true, value: "x" });
    resolveInteraction
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(undefined);

    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });
    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });

    expect(perform).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledTimes(2);
  });

  it("treats resolve 404 as settled (no-op) and does not re-resolve", async () => {
    const perform = vi.fn().mockResolvedValue({ ok: true, value: "x" });
    resolveInteraction.mockRejectedValue(new ApiError(404, "not found"));

    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });
    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });

    expect(perform).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledTimes(1);
  });

  it("allows re-perform after a failed side effect", async () => {
    const perform = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        error: { kind: "Boom", detail: "nope" },
      })
      .mockResolvedValueOnce({ ok: true, value: "ok" });

    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });
    await fulfillClientToolOnce({
      requestId: "r1",
      conversationId: "c1",
      logLabel: "test",
      perform,
    });

    expect(perform).toHaveBeenCalledTimes(2);
    expect(resolveInteraction).toHaveBeenCalledTimes(2);
  });
});
