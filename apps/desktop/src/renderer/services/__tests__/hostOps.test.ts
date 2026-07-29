import { beforeEach, describe, expect, it, vi } from "vitest";

const resolveInteraction = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/interaction", () => ({
  resolveInteraction: (...args: unknown[]) => resolveInteraction(...args),
}));

import { resetClientToolFulfillmentForTests } from "../clientToolFulfill";
import { performHostOp } from "../hostOps";
import type { HostOpRequiredPayload } from "@/types/events";

function payload(
  over: Partial<HostOpRequiredPayload> = {},
): HostOpRequiredPayload {
  return {
    request_id: "host-1",
    conversation_id: "conv-1",
    op: "shell",
    args: { command: "echo hi" },
    ...over,
  };
}

describe("performHostOp", () => {
  beforeEach(() => {
    resetClientToolFulfillmentForTests();
    resolveInteraction.mockClear();
    vi.stubGlobal("window", {
      hostApi: {
        runOp: vi.fn().mockResolvedValue({ ok: true, value: { code: 0 } }),
      },
    });
  });

  it("runs host op and posts client_tool result", async () => {
    await performHostOp(payload(), "conv-1");
    expect(window.hostApi?.runOp).toHaveBeenCalledWith({
      op: "shell",
      args: { command: "echo hi" },
    });
    expect(resolveInteraction).toHaveBeenCalledWith(
      "conv-1",
      "host-1",
      expect.objectContaining({
        kind: "client_tool",
        ok: true,
        value: { code: 0 },
      }),
    );
  });

  it("does not re-run host side effect on the same request_id", async () => {
    await performHostOp(payload(), "conv-1");
    await performHostOp(payload(), "conv-1");
    expect(window.hostApi?.runOp).toHaveBeenCalledTimes(1);
    expect(resolveInteraction).toHaveBeenCalledTimes(1);
  });
});
