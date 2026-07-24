import { FileArtifactsCard } from "@/components/chat/FileArtifactsCard";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { FileSource } from "@/lib/fileSource";
import { workspaceKeys } from "@/lib/queryKeys";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// @vitest-environment jsdom
import {
  type RenderResult,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { type ReactElement, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

function renderCard(ui: ReactElement): RenderResult {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
    },
  });
  // TurnFileChangesReview → useConversationWorkspace → useWorkspaces
  client.setQueryData(workspaceKeys.list, []);
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  );
}

const { showFile, openInAppPreview } = vi.hoisted(() => ({
  showFile: vi.fn(),
  openInAppPreview: vi.fn(),
}));

vi.mock("@/stores/disclosure", () => ({
  usePersistentDisclosure: (_key: string | null, initial: boolean) =>
    useState(initial),
}));

vi.mock("@/stores/sidePanel", () => ({
  useSidePanelStore: (sel: (s: { showFile: () => void }) => unknown) =>
    sel({ showFile }),
}));

vi.mock("@/hooks/useFileAudit", () => ({
  useFileAudit: () => ({ status: "idle" as const }),
}));

// 能力判定与对话侧栏同一套：卡直接问 useConversationFileSource 挂没挂 openInAppPreview。
vi.mock("@/hooks/useConversationFileSource", () => ({
  useConversationFileSource: vi.fn(() => null),
}));

import { useConversationFileSource } from "@/hooks/useConversationFileSource";

const sourceWithPreview = {
  openInAppPreview,
} as unknown as FileSource;

describe("FileArtifactsCard stage labels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useConversationFileSource).mockReturnValue(null);
  });

  it("research/debate 路径显示案卷标签，普通路径零噪音", () => {
    renderCard(
      <FileArtifactsCard
        conversationId="c1"
        artifacts={[
          { path: "research/brief.md", name: "brief.md", op: "write" },
          { path: "debate/round.md", name: "round.md", op: "write" },
          { path: "src/main.ts", name: "main.ts", op: "write" },
        ]}
      />,
    );
    expect(screen.getByText("调研案卷")).toBeTruthy();
    expect(screen.getByText("辩论产物")).toBeTruthy();
    expect(
      screen.getByTitle("在文件页查看案卷 research/brief.md"),
    ).toBeTruthy();
    expect(screen.getByTitle("在工作区预览 src/main.ts")).toBeTruthy();
    // 普通文件不应出现案卷标签（仅两处约定标签）
    expect(screen.getAllByText(/案卷|产物/).length).toBe(2);
  });
});

describe("FileArtifactsCard — HTML 产物直达完整预览", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useConversationFileSource).mockReturnValue(null);
  });

  it("会话具备完整预览能力：点 HTML 行直达完整预览 tab，非 HTML 仍走 showFile", () => {
    vi.mocked(useConversationFileSource).mockReturnValue(sourceWithPreview);
    renderCard(
      <FileArtifactsCard
        conversationId="c1"
        artifacts={[
          { path: "site/index.html", name: "index.html", op: "write" },
          { path: "data.csv", name: "data.csv", op: "write" },
        ]}
      />,
    );

    fireEvent.click(screen.getByTitle("打开完整预览 site/index.html"));
    expect(openInAppPreview).toHaveBeenCalledWith("site/index.html");
    expect(showFile).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTitle("在工作区预览 data.csv"));
    expect(showFile).toHaveBeenCalledWith("data.csv", "data.csv");
    expect(openInAppPreview).toHaveBeenCalledOnce();
  });

  it("无能力（本地会话 / web）：HTML 行回落 showFile 进文件视图", () => {
    renderCard(
      <FileArtifactsCard
        conversationId="c1"
        artifacts={[
          { path: "site/index.html", name: "index.html", op: "write" },
        ]}
      />,
    );

    fireEvent.click(screen.getByTitle("在工作区预览 site/index.html"));
    expect(showFile).toHaveBeenCalledWith("site/index.html", "index.html");
    expect(openInAppPreview).not.toHaveBeenCalled();
  });
});

describe("FileArtifactsCard — A1 查看改动", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useConversationFileSource).mockReturnValue(null);
  });

  it("有 change 预览时显示「查看改动」，点开只读面板", () => {
    renderCard(
      <FileArtifactsCard
        conversationId="c1"
        artifacts={[
          {
            path: "src/a.ts",
            name: "a.ts",
            op: "edit",
            change: { kind: "edit", oldText: "a", newText: "b" },
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByLabelText("查看改动"));
    expect(screen.getByText(/改动已写入工作区/)).toBeTruthy();
  });

  it("无 change 预览时不显示「查看改动」", () => {
    renderCard(
      <FileArtifactsCard
        conversationId="c1"
        artifacts={[{ path: "src/a.ts", name: "a.ts", op: "write" }]}
      />,
    );
    expect(screen.queryByLabelText("查看改动")).toBeNull();
  });
});
