import { beforeEach, describe, expect, it, vi } from "vitest";

const resolveInteraction = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/interaction", () => ({
  resolveInteraction: (...args: unknown[]) => resolveInteraction(...args),
}));

import type { McpOpRequiredPayload } from "@/types/events";
import { resetClientToolFulfillmentForTests } from "../clientToolFulfill";
import { performMcpOp } from "../mcpOps";

function payload(
  over: Partial<McpOpRequiredPayload> = {},
): McpOpRequiredPayload {
  return {
    request_id: "mcp-1",
    conversation_id: "conv-1",
    op: "list_tools",
    args: {},
    ...over,
  };
}

describe("performMcpOp", () => {
  beforeEach(() => {
    resetClientToolFulfillmentForTests();
    resolveInteraction.mockClear();
    vi.stubGlobal("window", {
      mcpApi: {
        runOp: vi.fn().mockResolvedValue({ ok: true, value: { servers: [] } }),
        listServers: vi.fn(),
        upsertServer: vi.fn(),
        removeServer: vi.fn(),
        setServerEnabled: vi.fn(),
        testServer: vi.fn(),
      },
    });
  });

  it("runs mcp op and posts client_tool result", async () => {
    await performMcpOp(payload(), "conv-1");
    expect(window.mcpApi?.runOp).toHaveBeenCalledWith({
      op: "list_tools",
      args: {},
    });
    expect(resolveInteraction).toHaveBeenCalled();
  });

  it("dedupes the same request_id", async () => {
    await performMcpOp(payload(), "conv-1");
    await performMcpOp(payload(), "conv-1");
    expect(window.mcpApi?.runOp).toHaveBeenCalledTimes(1);
  });
});
