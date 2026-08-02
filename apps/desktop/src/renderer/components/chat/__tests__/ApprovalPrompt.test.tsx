// @vitest-environment jsdom
import { ApprovalCard } from "@/components/chat/ApprovalPrompt";
import { TooltipProvider } from "@/components/ui/tooltip";
import { patchConversationCache } from "@/hooks/useConversations";
import { setConversationPermissionAxes } from "@/services/permissionAxes";
import type { ApprovalView } from "@/stores/interactions";
import { useInteractionStore } from "@/stores/interactions";
import { usePermissionChangeStore } from "@/stores/permissionChanges";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useConversations", () => ({
  getConversations: () => [
    {
      id: "c1",
      permissionAxes: {
        file_write: "session",
        command: "kickoff",
        team_kickoff: "rules",
        host: "ask",
      },
    },
  ],
  patchConversationCache: vi.fn(),
}));

vi.mock("@/services/permissionAxes", () => ({
  setConversationPermissionAxes: vi.fn(),
  matchRecipe: () => "less_interrupt",
  recipeToAxes: () => ({
    file_write: "session",
    command: "auto",
    team_kickoff: "skip",
    host: "session",
  }),
}));

vi.mock("@/services/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/approvals")>();
  return { ...actual, decideApproval: vi.fn() };
});

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));

afterEach(() => {
  cleanup();
  useInteractionStore.setState({ byId: new Map() });
});

beforeEach(() => {
  vi.mocked(setConversationPermissionAxes).mockReset();
  vi.mocked(patchConversationCache).mockReset();
});

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

/** Seed enough same-tool approvals so the「托管」nudge appears. */
function seedSameToolApprovals(n: number, toolName = "terminal") {
  const byId = new Map();
  for (let i = 0; i < n; i++) {
    byId.set(`hist-${i}`, {
      id: `hist-${i}`,
      kind: "approval" as const,
      status: "resolved" as const,
      conversationId: "c1",
      messageId: "m1",
      payload: { tool_name: toolName, approval_id: `hist-${i}` },
    });
  }
  useInteractionStore.setState({ byId });
}

describe("ApprovalCard git headline", () => {
  it("shows push → remote for git push approvals", () => {
    renderCard(
      card({
        toolName: "git",
        arguments: { subcommand: "push", remote: "origin" },
      }),
    );
    expect(screen.getByText("push → origin")).toBeTruthy();
  });

  it("defaults push remote to origin when omitted", () => {
    renderCard(
      card({
        toolName: "git",
        arguments: { subcommand: "push" },
      }),
    );
    expect(screen.getByText("push → origin")).toBeTruthy();
  });

  it("shows commit + message snippet", () => {
    renderCard(
      card({
        toolName: "git",
        arguments: {
          subcommand: "commit",
          message: "fix approval headline for push",
        },
      }),
    );
    expect(
      screen.getByText("commit fix approval headline for push"),
    ).toBeTruthy();
  });

  it("falls back to subcommand when no extra args", () => {
    renderCard(
      card({
        toolName: "git",
        arguments: { subcommand: "status" },
      }),
    );
    expect(screen.getByText("status")).toBeTruthy();
  });
});

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

  it("switching to 托管 patches cache and reloads permission change lines", async () => {
    seedSameToolApprovals(3);
    const managed = {
      file_write: "session" as const,
      command: "auto" as const,
      team_kickoff: "skip" as const,
      host: "session" as const,
    };
    vi.mocked(setConversationPermissionAxes).mockResolvedValue(managed);
    const load = vi.fn().mockResolvedValue(undefined);
    usePermissionChangeStore.setState({ load });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderCard(card());
    fireEvent.click(screen.getByRole("button", { name: "托管" }));

    await waitFor(() => {
      expect(setConversationPermissionAxes).toHaveBeenCalledWith("c1", managed);
      expect(patchConversationCache).toHaveBeenCalledWith("c1", {
        permissionAxes: managed,
      });
      expect(load).toHaveBeenCalledWith("c1");
    });
  });
});
