import { beforeEach, describe, expect, it, vi } from "vitest";

const acceptRunOutcome = vi.fn().mockResolvedValue({ recorded: true });
const clearExecution = vi.fn();
const projectRuntime = vi.fn();

vi.mock("@/services/runRedirect", () => ({
  acceptRunOutcome: (...args: unknown[]) => acceptRunOutcome(...args),
}));

vi.mock("@/stores/conversation", () => ({
  assistantProjectionId: (m: { id: string }) => m.id,
  getRuntime: () => ({
    messages: [
      {
        id: "u1",
        role: "user",
        content: "q",
        createdAt: "",
        executionId: null,
        isStreaming: false,
      },
      {
        id: "a1",
        role: "assistant",
        content: "a",
        createdAt: "",
        executionId: "e1",
        isStreaming: false,
      },
    ],
  }),
}));

vi.mock("@/stores/execution", () => ({
  execRuntime: () => ({ plan: { id: "p1" } }),
  projectRuntime: (...args: unknown[]) => projectRuntime(...args),
  useExecutionStore: {
    getState: () => ({ clearExecution }),
  },
}));

describe("dismissRecoverableExecutions", () => {
  beforeEach(() => {
    acceptRunOutcome.mockClear();
    clearExecution.mockClear();
    projectRuntime.mockReset();
  });

  it("audits recovery_ignored and clears recoverable slots", async () => {
    projectRuntime.mockReturnValue({
      status: "failed",
      runs: [{ status: "failed" }],
    });
    const { dismissRecoverableExecutions } = await import(
      "../turns/dismissRecovery"
    );
    dismissRecoverableExecutions("conv-1");
    expect(acceptRunOutcome).toHaveBeenCalledWith(
      "conv-1",
      expect.objectContaining({
        messageId: "a1",
        reason: "recovery_ignored",
      }),
    );
    expect(clearExecution).toHaveBeenCalledWith("a1");
  });

  it("skips non-recoverable executions", async () => {
    projectRuntime.mockReturnValue({
      status: "completed",
      runs: [{ status: "completed" }],
    });
    const { dismissRecoverableExecutions } = await import(
      "../turns/dismissRecovery"
    );
    dismissRecoverableExecutions("conv-1");
    expect(acceptRunOutcome).not.toHaveBeenCalled();
    expect(clearExecution).not.toHaveBeenCalled();
  });
});
