import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StreamNetworkError, pumpSSEForTests } from "../stream";

describe("pumpSSE idle watchdog", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("rejects after 60s of silence on an open body", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start() {
        /* never enqueues — simulates a dead socket */
      },
    });
    const onEvent = vi.fn();
    const pump = pumpSSEForTests(new Response(stream), onEvent);
    const expectReject =
      expect(pump).rejects.toBeInstanceOf(StreamNetworkError);
    await vi.advanceTimersByTimeAsync(60_001);
    await expectReject;
    expect(onEvent).not.toHaveBeenCalled();
  });
});
