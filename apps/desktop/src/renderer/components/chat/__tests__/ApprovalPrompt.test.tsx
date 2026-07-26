// @vitest-environment jsdom
import { ApprovalCard } from "@/components/chat/ApprovalPrompt";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ApprovalView } from "@/stores/interactions";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useConversations", () => ({
  getConversations: () => [{ id: "c1", permissionPreset: "workspace" }],
  patchConversationCache: vi.fn(),
}));

vi.mock("@/services/permissionPreset", () => ({
  setConversationPermissionPreset: vi.fn(),
}));

vi.mock("@/services/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/approvals")>();
  return { ...actual, decideApproval: vi.fn() };
});

afterEach(cleanup);

function card(over: Partial<ApprovalView> = {}): ApprovalView {
  return {
    approvalId: "a1",
    conversationId: "c1",
    toolCallId: "a1",
    toolName: "terminal",
    arguments: { subcommand: "start", command: "pnpm dev" },
    resolving: false,
    ...over,
  };
}

function renderCard(approval: ApprovalView) {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <ApprovalCard approval={approval} onDecide={() => {}} />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

describe("ApprovalCard CTA (工具审批 A+B)", () => {
  it("execution tools put 本轮内都允许 as the primary button", () => {
    renderCard(card());
    const buttons = screen.getAllByRole("button");
    const labels = buttons.map((b) => b.textContent ?? "");
    const turnIdx = labels.findIndex((t) => t.includes("本轮内都允许"));
    const onceIdx = labels.findIndex((t) => t.includes("允许一次"));
    expect(turnIdx).toBeGreaterThanOrEqual(0);
    expect(onceIdx).toBeGreaterThanOrEqual(0);
    expect(turnIdx).toBeLessThan(onceIdx);
  });

  it("file tools keep 允许一次 before 本轮内都允许", () => {
    renderCard(
      card({
        toolName: "file_write",
        arguments: { path: "a.txt", content: "x" },
      }),
    );
    const buttons = screen.getAllByRole("button");
    const labels = buttons.map((b) => b.textContent ?? "");
    const turnIdx = labels.findIndex((t) => t.includes("本轮内都允许"));
    const onceIdx = labels.findIndex((t) => t.includes("允许一次"));
    expect(onceIdx).toBeLessThan(turnIdx);
  });
});
