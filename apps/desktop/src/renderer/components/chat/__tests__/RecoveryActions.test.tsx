// @vitest-environment jsdom
import { ExecutionScopeContext } from "@/stores/execution";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecoveryActions } from "../StatusStrip";

const runRetryFailed = vi.fn();
const runRegenerate = vi.fn();

vi.mock("@/services/turns", () => ({
  lastUserMessageId: () => "user-1",
  runRetryFailed: (...args: unknown[]) => runRetryFailed(...args),
  runRegenerate: (...args: unknown[]) => runRegenerate(...args),
}));

vi.mock("@/stores/conversation", async () => {
  const actual = await vi.importActual<typeof import("@/stores/conversation")>(
    "@/stores/conversation",
  );
  return {
    ...actual,
    useActiveGenerating: () => false,
    useConversationStore: (
      sel: (s: { currentConversationId: string }) => unknown,
    ) => sel({ currentConversationId: "conv-1" }),
    getActiveRuntime: () => ({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "hi",
          createdAt: "",
          executionId: null,
          isStreaming: false,
        },
        {
          id: "asst-1",
          role: "assistant",
          content: "bye",
          createdAt: "",
          executionId: "e1",
          isStreaming: false,
        },
      ],
    }),
  };
});

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  runRetryFailed.mockReset();
  runRegenerate.mockReset();
});

function mount(hasFailedRuns: boolean) {
  return render(
    <ExecutionScopeContext.Provider value="asst-1">
      <RecoveryActions hasFailedRuns={hasFailedRuns} />
    </ExecutionScopeContext.Provider>,
  );
}

describe("RecoveryActions · inline links", () => {
  it("partial failure shows only retry-failed (no regenerate stack, no ignore)", () => {
    mount(true);
    expect(screen.getByRole("button", { name: "重试失败项" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    expect(screen.queryByRole("button", { name: "全部重新生成" })).toBeNull();
    expect(screen.queryByRole("button", { name: "忽略" })).toBeNull();
    expect(screen.queryByRole("button", { name: "放弃" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重试失败项" }));
    expect(runRetryFailed).toHaveBeenCalledWith("user-1");
  });

  it("full failure / stopped shows only regenerate", () => {
    mount(false);
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重试失败项" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(runRegenerate).toHaveBeenCalledWith("user-1");
  });
});
