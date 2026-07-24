// @vitest-environment jsdom
/**
 * Render + interaction tests for the mobile 交互式暂停放行 card (前端技术与架构 §七, AUD-012).
 *
 * PauseCard turns the conformance-folded `pendingInteraction` into the actionable buttons that
 * POST the user's decision to the live SSE (api/interaction.resolveInteraction). 挂起即收口
 * (②, Phase 3): only an `approval` resolves live in-stream now — a checkpoint (ask_user) /
 * plan_review finalizes the turn and is continued via the durable ResumeCard, so PauseCard
 * handles approvals only. These assert the per-tool button gating that mirrors the backend gate
 * (code_execute hides「本轮都允许」per PI-004; file ops add the class grant), that each click
 * submits the right discriminated body, and the error path. The block comment keeps the
 * @vitest-environment directive file-leading past organizeImports.
 */

import { resolveInteraction } from "@/api/interaction";
import { PauseCard } from "@/components/PauseCard";
import type { ProjectedInteraction } from "@agentcore/protocol-conformance";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/interaction", () => ({ resolveInteraction: vi.fn() }));
const mockResolve = vi.mocked(resolveInteraction);

const CONV = "conv-1";

afterEach(cleanup);
beforeEach(() => {
  mockResolve.mockReset();
  mockResolve.mockResolvedValue(undefined);
});

function approval(
  over: Partial<Extract<ProjectedInteraction, { kind: "approval" }>> = {},
): Extract<ProjectedInteraction, { kind: "approval" }> {
  return {
    kind: "approval",
    id: "appr-1",
    status: "pending",
    toolCallId: "tc-1",
    toolName: "file_write",
    arguments: { path: "/tmp/x" },
    ...over,
  };
}

describe("PauseCard · approval", () => {
  it("renders the 中文 tool label + headline arg and the full button set for a file op", () => {
    render(<PauseCard pending={approval()} conversationId={CONV} />);
    expect(screen.getByText("Agent 请求执行 · 写入文件")).toBeTruthy();
    expect(screen.getByText("/tmp/x")).toBeTruthy();
    expect(screen.getByText("允许一次")).toBeTruthy();
    expect(screen.getByText("本轮都允许")).toBeTruthy();
    // file_write ∈ FILE_OP_TOOLS → the class grant is offered.
    expect(screen.getByText("本轮内所有文件改动")).toBeTruthy();
    expect(screen.getByText("拒绝")).toBeTruthy();
  });

  it("submits an `approve` decision to resolveInteraction with the approvalId", async () => {
    render(<PauseCard pending={approval()} conversationId={CONV} />);
    fireEvent.click(screen.getByText("允许一次"));
    await waitFor(() =>
      expect(mockResolve).toHaveBeenCalledWith(CONV, "appr-1", {
        kind: "approval",
        decision: "approve",
      }),
    );
    // On success the card stays busy until the stream's *_resolved unmounts it.
    expect(screen.getByText("处理中…")).toBeTruthy();
  });

  it("submits `deny` and `approve_always_files` from the matching buttons", async () => {
    render(<PauseCard pending={approval()} conversationId={CONV} />);
    fireEvent.click(screen.getByText("本轮内所有文件改动"));
    await waitFor(() =>
      expect(mockResolve).toHaveBeenLastCalledWith(CONV, "appr-1", {
        kind: "approval",
        decision: "approve_always_files",
      }),
    );

    cleanup();
    render(<PauseCard pending={approval()} conversationId={CONV} />);
    fireEvent.click(screen.getByText("拒绝"));
    await waitFor(() =>
      expect(mockResolve).toHaveBeenLastCalledWith(CONV, "appr-1", {
        kind: "approval",
        decision: "deny",
      }),
    );
  });

  it("shows「本轮都允许」for code_execute (Cursor-aligned turn grant)", () => {
    render(
      <PauseCard
        pending={approval({
          toolName: "code_execute",
          arguments: { command: "ls" },
        })}
        conversationId={CONV}
      />,
    );
    expect(screen.getByText("Agent 请求执行 · 执行代码")).toBeTruthy();
    expect(screen.getByText("允许一次")).toBeTruthy();
    expect(screen.getByText("本轮都允许")).toBeTruthy();
    expect(screen.getByText("拒绝")).toBeTruthy();
    // code_execute ∉ FILE_OP_TOOLS — file-class grant still hidden.
    expect(screen.queryByText("本轮内所有文件改动")).toBeNull();
  });

  it("surfaces an error and re-enables the card when the POST fails", async () => {
    mockResolve.mockRejectedValueOnce(new Error("放行失败 (500)"));
    render(<PauseCard pending={approval()} conversationId={CONV} />);
    fireEvent.click(screen.getByText("允许一次"));
    expect(await screen.findByText("放行失败 (500)")).toBeTruthy();
    // busy cleared on failure → no「处理中…」, the buttons are clickable again.
    expect(screen.queryByText("处理中…")).toBeNull();
  });
});
