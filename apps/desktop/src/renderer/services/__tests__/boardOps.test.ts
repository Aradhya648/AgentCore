import { beforeEach, describe, expect, it, vi } from "vitest";

const resolveInteraction = vi.fn().mockResolvedValue(undefined);
vi.mock("@/services/interaction", () => ({
  resolveInteraction: (...args: unknown[]) => resolveInteraction(...args),
}));
vi.mock("@/lib/toast", () => ({ notifyInfo: vi.fn() }));

import type { BoardOpRequiredPayload } from "@/types/events";
import { performBoardOp, registerBoardApplier } from "../boardOps";
import { resetClientToolFulfillmentForTests } from "../clientToolFulfill";

function payload(
  over: Partial<BoardOpRequiredPayload> = {},
): BoardOpRequiredPayload {
  return {
    request_id: "board-1",
    conversation_id: "conv-1",
    board_id: "b1",
    ops: [],
    summary: "draw",
    ...over,
  };
}

describe("performBoardOp", () => {
  beforeEach(() => {
    resetClientToolFulfillmentForTests();
    resolveInteraction.mockClear();
  });

  it("does not re-apply ops on the same request_id", async () => {
    const applier = vi.fn().mockResolvedValue({
      applied: 1,
      created: ["el-1"],
      version: 2,
    });
    const unregister = registerBoardApplier("b1", applier);

    await performBoardOp(payload(), "conv-1");
    await performBoardOp(payload(), "conv-1");

    expect(applier).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledTimes(1);
    unregister();
  });
});
