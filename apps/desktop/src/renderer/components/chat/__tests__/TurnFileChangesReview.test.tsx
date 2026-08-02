import { TurnFileChangesReview } from "@/components/chat/TurnFileChangesReview";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { WorkspaceInfo } from "@/services/workspaces";
// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { type Mock, beforeEach, describe, expect, it, vi } from "vitest";

const {
  getTurnFilesDiff,
  getLocalTurnFilesDiff,
  restoreLocalTurnBaseline,
  restoreSnapshot,
  notifySuccess,
  useConversationWorkspace,
} = vi.hoisted(() => ({
  getTurnFilesDiff: vi.fn(),
  getLocalTurnFilesDiff: vi.fn(),
  restoreLocalTurnBaseline: vi.fn(),
  restoreSnapshot: vi.fn(),
  notifySuccess: vi.fn(),
  useConversationWorkspace: vi.fn((): WorkspaceInfo | null => null) as Mock<
    () => WorkspaceInfo | null
  >,
}));

vi.mock("@/services/turnFilesDiff", () => ({
  getTurnFilesDiff,
  getLocalTurnFilesDiff,
  restoreLocalTurnBaseline,
}));
vi.mock("@/services/workspace", () => ({ restoreSnapshot }));
vi.mock("@/lib/toast", () => ({
  notifySuccess,
  notifyActionError: vi.fn(),
}));
vi.mock("@/hooks/useWorkspaces", () => ({
  useConversationWorkspace,
}));

describe("TurnFileChangesReview change labels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConversationWorkspace.mockReturnValue(null);
  });

  it("true diff labels by baseline presence: 新建/更新/删除 (never 写入/编辑)", async () => {
    getTurnFilesDiff.mockResolvedValue({
      messageId: "m1",
      baselineSnapshotId: "snap-1",
      available: true,
      changes: [
        {
          path: "new.ts",
          changeType: "added",
          baseSha: null,
          resultSha: "r1",
          isBinary: false,
          content: "hello",
          sizeBytes: 5,
          baseContent: null,
        },
        {
          path: "old.ts",
          changeType: "modified",
          baseSha: "b",
          resultSha: "r2",
          isBinary: false,
          content: "new",
          sizeBytes: 3,
          baseContent: "old",
        },
        {
          path: "gone.ts",
          changeType: "deleted",
          baseSha: "b",
          resultSha: null,
          isBinary: false,
          content: null,
          sizeBytes: 0,
          baseContent: "x",
        },
      ],
      total: 3,
      added: 1,
      modified: 1,
      deleted: 1,
    });

    render(
      <TooltipProvider>
        <TurnFileChangesReview
          conversationId="c1"
          messageId="m1"
          artifacts={[]}
        />
      </TooltipProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("新建")).toBeTruthy();
      expect(screen.getByText("更新")).toBeTruthy();
      expect(screen.getByText("删除")).toBeTruthy();
    });
    expect(screen.queryByText("写入")).toBeNull();
    expect(screen.queryByText("编辑")).toBeNull();
    expect(screen.queryByText("新增")).toBeNull();
    expect(screen.queryByText("修改")).toBeNull();
    // 单层 chrome：行数在折叠头，不在展开体内再标路径/模式
    expect(screen.getByText("1 行")).toBeTruthy();
    expect(screen.getAllByText("+1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("-1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("old.ts")).toHaveLength(1);
    expect(screen.getAllByText("new.ts")).toHaveLength(1);
  });

  it("tool-arg fallback labels write/edit as 更新, never 写入/编辑", async () => {
    getTurnFilesDiff.mockResolvedValue({
      messageId: "m1",
      baselineSnapshotId: null,
      available: false,
      changes: [],
      total: 0,
      added: 0,
      modified: 0,
      deleted: 0,
    });

    render(
      <TooltipProvider>
        <TurnFileChangesReview
          conversationId="c1"
          messageId="m1"
          artifacts={[
            {
              path: "a.ts",
              name: "a.ts",
              op: "write",
              change: {
                kind: "write",
                content: "body",
                mode: "overwrite",
              },
            },
            {
              path: "b.ts",
              name: "b.ts",
              op: "edit",
              change: { kind: "edit", oldText: "a", newText: "b" },
            },
            {
              path: "c.ts",
              name: "c.ts",
              op: "delete",
              change: { kind: "delete" },
            },
          ]}
        />
      </TooltipProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/工具参数侧预览/)).toBeTruthy();
    });
    // Row labels: write+edit → 更新; delete → 删除
    expect(screen.getAllByText("更新").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("删除")).toBeTruthy();
    expect(screen.queryByText("写入")).toBeNull();
    expect(screen.queryByText("编辑")).toBeNull();
    // 单层 chrome：write 模式行数在折叠头；路径不重复
    expect(screen.getByText("1 行")).toBeTruthy();
    expect(screen.getAllByText("a.ts")).toHaveLength(1);
    expect(screen.getAllByText("b.ts")).toHaveLength(1);
  });
});

describe("TurnFileChangesReview A2′ rollback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConversationWorkspace.mockReturnValue(null);
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
  });

  it("shows rollback when true diff has baseline, and restores on confirm", async () => {
    getTurnFilesDiff.mockResolvedValue({
      messageId: "m1",
      baselineSnapshotId: "snap-1",
      available: true,
      changes: [
        {
          path: "a.ts",
          changeType: "modified",
          baseSha: "b",
          resultSha: "r",
          isBinary: false,
          content: "new",
          sizeBytes: 3,
          baseContent: "old",
        },
      ],
      total: 1,
      added: 0,
      modified: 1,
      deleted: 0,
    });
    restoreSnapshot.mockResolvedValue(undefined);

    render(
      <TooltipProvider>
        <TurnFileChangesReview
          conversationId="c1"
          messageId="m1"
          artifacts={[
            {
              path: "a.ts",
              name: "a.ts",
              op: "edit",
              change: { kind: "edit", oldText: "old", newText: "new" },
            },
          ]}
        />
      </TooltipProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("回退到本回合开始")).toBeTruthy();
    });

    fireEvent.click(screen.getByLabelText("回退到本回合开始"));
    await waitFor(() => {
      expect(restoreSnapshot).toHaveBeenCalledWith("c1", "snap-1");
      expect(notifySuccess).toHaveBeenCalled();
    });
    expect(getLocalTurnFilesDiff).not.toHaveBeenCalled();
    expect(restoreLocalTurnBaseline).not.toHaveBeenCalled();
  });

  it("hides rollback when falling back to tool-arg preview", async () => {
    getTurnFilesDiff.mockResolvedValue({
      messageId: "m1",
      baselineSnapshotId: null,
      available: false,
      changes: [],
      total: 0,
      added: 0,
      modified: 0,
      deleted: 0,
    });

    render(
      <TooltipProvider>
        <TurnFileChangesReview
          conversationId="c1"
          messageId="m1"
          artifacts={[
            {
              path: "a.ts",
              name: "a.ts",
              op: "edit",
              change: { kind: "edit", oldText: "a", newText: "b" },
            },
          ]}
        />
      </TooltipProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/工具参数侧预览/)).toBeTruthy();
    });
    expect(screen.queryByLabelText("回退到本回合开始")).toBeNull();
  });

  it("uses sidecar local diff/restore when workspace location is local", async () => {
    useConversationWorkspace.mockReturnValue({
      wsId: "conv:c1",
      name: "c1",
      location: "local",
      rootId: "root-1",
      subpath: "conversations/c1",
      hasFiles: true,
    });
    getLocalTurnFilesDiff.mockResolvedValue({
      messageId: "m1",
      baselineSnapshotId: "m1",
      available: true,
      changes: [],
      total: 0,
      added: 0,
      modified: 0,
      deleted: 0,
    });
    restoreLocalTurnBaseline.mockResolvedValue(undefined);

    render(
      <TooltipProvider>
        <TurnFileChangesReview
          conversationId="c1"
          messageId="m1"
          artifacts={[
            {
              path: "a.ts",
              name: "a.ts",
              op: "edit",
              change: { kind: "edit", oldText: "a", newText: "b" },
            },
          ]}
        />
      </TooltipProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("回退到本回合开始")).toBeTruthy();
    });
    expect(getLocalTurnFilesDiff).toHaveBeenCalledWith(
      { rootId: "root-1", subpath: "conversations/c1" },
      "m1",
    );
    expect(getTurnFilesDiff).not.toHaveBeenCalled();
    expect(screen.getByText(/本机工作区基线/)).toBeTruthy();

    fireEvent.click(screen.getByLabelText("回退到本回合开始"));
    await waitFor(() => {
      expect(restoreLocalTurnBaseline).toHaveBeenCalledWith(
        { rootId: "root-1", subpath: "conversations/c1" },
        "m1",
      );
    });
    expect(restoreSnapshot).not.toHaveBeenCalled();
  });
});
