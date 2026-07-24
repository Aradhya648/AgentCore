// @vitest-environment jsdom
/**
 * D2「已授权 · 执行中断」卡：渲染条件 + 一键继续绑定 continueAfterDecision。
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResumePrompt } from "../ResumePrompt";

const runContinueAfterDecision = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/interactionSubmit", () => ({
  submitInteraction: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
}));

vi.mock("@/services/turns", () => ({
  runContinueAfterDecision: (...args: unknown[]) =>
    runContinueAfterDecision(...args),
}));

vi.mock("@/stores/conversation", () => ({
  useConversationStore: (
    sel: (s: { currentConversationId: string }) => unknown,
  ) => sel({ currentConversationId: "c1" }),
}));

vi.mock("@/stores/pausedTurns", () => ({
  usePausedTurnStore: (sel: (s: { pending: unknown[] }) => unknown) =>
    sel({ pending: [] }),
}));

vi.mock("@/stores/interactions", () => ({
  useInteractionStore: (sel: (s: { byId: Map<string, unknown> }) => unknown) =>
    sel({ byId: new Map() }),
}));

const interruptedRef: {
  current: Array<{
    messageId: string;
    userMessageId: string;
    conversationId: string;
    settledKind: string;
    checkpointId: string;
  }>;
} = { current: [] };

vi.mock("@/stores/interruptedAfterDecision", () => ({
  useInterruptedAfterDecisionStore: (
    sel: (s: { byConversation: Record<string, unknown[]> }) => unknown,
  ) =>
    sel({
      byConversation: { c1: interruptedRef.current },
    }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  interruptedRef.current = [];
});

beforeEach(() => {
  interruptedRef.current = [
    {
      messageId: "m-interrupt",
      userMessageId: "u1",
      conversationId: "c1",
      settledKind: "team_preview",
      checkpointId: "tp1",
    },
  ];
});

describe("ResumePrompt · interrupted_after_decision", () => {
  it("renders 已授权 · 执行中断 when store has entry and no paused frame", () => {
    render(<ResumePrompt />);
    expect(screen.getByText("已授权 · 执行中断")).toBeTruthy();
    expect(screen.getByText("一键继续")).toBeTruthy();
    expect(screen.queryByText("授权并开工")).toBeNull();
    expect(screen.queryByText("授权开赛")).toBeNull();
  });

  it("一键继续 calls runContinueAfterDecision with messageId", async () => {
    render(<ResumePrompt />);
    fireEvent.click(screen.getByText("一键继续"));
    await waitFor(() => {
      expect(runContinueAfterDecision).toHaveBeenCalledWith("m-interrupt");
    });
  });

  it("renders nothing when neither paused nor interrupted", () => {
    interruptedRef.current = [];
    const { container } = render(<ResumePrompt />);
    expect(container.firstChild).toBeNull();
  });
});
