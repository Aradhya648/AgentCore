import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  HARVEST_REFRESH_DELAYS_MS,
  createHarvestRefreshScheduler,
  dropSettledLiveTurns,
} from "../refreshAfterExecutionCompleted";

describe("dropSettledLiveTurns", () => {
  it("丢弃已 message_end 的 live turn，保留未收口 turn", () => {
    const turns = [
      {
        id: "host",
        events: [{ type: "content_delta" }, { type: "message_end" }],
      },
      { id: "turn2", events: [{ type: "content_delta" }] },
    ];
    expect(dropSettledLiveTurns(turns).map((t) => t.id)).toEqual(["turn2"]);
  });

  it("无 message_end 时原样保留", () => {
    const turns = [{ id: "live", events: [{ type: "run_started" }] }];
    expect(dropSettledLiveTurns(turns)).toEqual(turns);
  });
});

describe("createHarvestRefreshScheduler", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("schedule 在 0 / 1.5s / 6s 触发 reload", async () => {
    const reload = vi.fn().mockResolvedValue(undefined);
    const sched = createHarvestRefreshScheduler(reload);
    sched.schedule("conv-1");

    expect(reload).toHaveBeenCalledTimes(1);
    expect(reload.mock.calls[0]?.[0]).toBe("conv-1");

    await vi.advanceTimersByTimeAsync(1500);
    expect(reload).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(4500);
    expect(reload).toHaveBeenCalledTimes(3);
    expect(HARVEST_REFRESH_DELAYS_MS).toEqual([0, 1500, 6000]);
  });

  it("cancel 后延迟重试不再调用", async () => {
    const reload = vi.fn().mockResolvedValue(undefined);
    const sched = createHarvestRefreshScheduler(reload);
    sched.schedule("conv-1");
    expect(reload).toHaveBeenCalledTimes(1);

    sched.cancel();
    await vi.advanceTimersByTimeAsync(6000);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("cancel 后进行中的 reload 不得写回（isCurrent=false）", async () => {
    let resolveReload!: () => void;
    const sawCurrent: boolean[] = [];
    const reload = vi.fn(
      (_cid: string, isCurrent: () => boolean) =>
        new Promise<void>((resolve) => {
          sawCurrent.push(isCurrent());
          resolveReload = () => {
            sawCurrent.push(isCurrent());
            resolve();
          };
        }),
    );
    const sched = createHarvestRefreshScheduler(reload);
    sched.schedule("conv-1");
    expect(reload).toHaveBeenCalledTimes(1);
    expect(sawCurrent[0]).toBe(true);

    sched.cancel();
    resolveReload();
    await Promise.resolve();
    expect(sawCurrent[1]).toBe(false);
  });

  it("reload 失败不抛（best-effort）", async () => {
    const reload = vi.fn().mockRejectedValue(new Error("network"));
    const sched = createHarvestRefreshScheduler(reload);
    expect(() => sched.schedule("conv-1")).not.toThrow();
    await vi.advanceTimersByTimeAsync(0);
    expect(reload).toHaveBeenCalled();
  });
});
