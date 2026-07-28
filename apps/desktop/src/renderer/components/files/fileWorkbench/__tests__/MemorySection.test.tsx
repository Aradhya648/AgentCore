// @vitest-environment jsdom
/**
 * MemorySection —「记忆」under AgentCore convention tree:
 * GLOBAL lists 最近更新 / 偏好 / 画像 / 主题; project scope is 画像 + 主题.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/memory", () => ({
  listMemoryTopics: vi.fn(),
  writeMemoryTopic: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({
  notifyActionError: vi.fn(),
  notifySuccess: vi.fn(),
}));

import { listMemoryTopics, writeMemoryTopic } from "@/services/memory";
import {
  GLOBAL_PREFERENCES_PATH,
  memoryProjectProfilePath,
  memoryTopicPath,
  parseProjectProfilePath,
} from "@/services/sources/memorySource";
import { MemorySection } from "../MemorySection";

function renderGlobal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onOpen = vi.fn();
  const onTopicDeleted = vi.fn();
  const onOpenUpdates = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemorySection
          scope={{ kind: "global" }}
          activePath={null}
          onOpen={onOpen}
          onTopicDeleted={onTopicDeleted}
          onOpenUpdates={onOpenUpdates}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { onOpen, onTopicDeleted, onOpenUpdates };
}

function renderProject(folderId = "F1", projectName = "项目甲") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onOpen = vi.fn();
  const onTopicDeleted = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemorySection
          scope={{ kind: "project", folderId, projectName }}
          activePath={null}
          onOpen={onOpen}
          onTopicDeleted={onTopicDeleted}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { onOpen, onTopicDeleted };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(listMemoryTopics).mockResolvedValue([]);
  vi.mocked(writeMemoryTopic).mockResolvedValue({
    ok: true,
    version: "v1",
  } as never);
});

afterEach(cleanup);

describe("MemorySection (global)", () => {
  it("lists GLOBAL core leaves without a 项目记忆 aggregator", () => {
    const { onOpen } = renderGlobal();

    expect(screen.getByText("记忆")).toBeTruthy();
    expect(screen.getByText("最近更新")).toBeTruthy();
    expect(screen.getByText("画像")).toBeTruthy();
    expect(screen.getByText("主题")).toBeTruthy();
    expect(screen.queryByText("项目记忆")).toBeNull();
    expect(screen.queryByText("AI 记忆")).toBeNull();

    fireEvent.click(screen.getByText("偏好"));
    expect(onOpen).toHaveBeenCalledWith(GLOBAL_PREFERENCES_PATH, "偏好.md");
  });
});

describe("MemorySection (project)", () => {
  it("shows a fixed 记忆 header and opens project 画像", () => {
    const { onOpen } = renderProject();

    expect(screen.getByText("记忆")).toBeTruthy();
    expect(screen.queryByText("项目记忆")).toBeNull();
    expect(screen.queryByText("AI 记忆")).toBeNull();

    // Project sections default collapsed.
    fireEvent.click(screen.getByText("记忆"));
    fireEvent.click(screen.getByText("画像"));

    expect(onOpen).toHaveBeenCalledWith(
      memoryProjectProfilePath("F1"),
      "项目甲·画像.md",
    );
    const openedPath = onOpen.mock.calls[0][0] as string;
    expect(parseProjectProfilePath(openedPath)).toBe("F1");
  });

  it("lists project topics without a list-tail 新建主题假行", async () => {
    vi.mocked(listMemoryTopics).mockResolvedValue(["部署流程"]);
    const { onOpen } = renderProject();

    fireEvent.click(screen.getByText("记忆"));
    fireEvent.click(screen.getByText("主题"));

    expect(await screen.findByText("部署流程.md")).toBeTruthy();
    expect(listMemoryTopics).toHaveBeenCalledWith("F1");
    // Create hangs on the「主题」header (aria/title), not a list-tail fake row.
    expect(screen.getByLabelText("新建主题")).toBeTruthy();
    expect(screen.queryByText("新建主题")).toBeNull();

    fireEvent.click(screen.getByText("部署流程.md"));
    expect(onOpen).toHaveBeenCalledWith(
      memoryTopicPath("F1", "部署流程"),
      "部署流程.md",
    );
  });

  it("creates a project topic from the 主题 header +", async () => {
    vi.mocked(listMemoryTopics).mockResolvedValue(["部署流程"]);
    vi.spyOn(window, "prompt").mockReturnValue("发布清单");
    const { onOpen } = renderProject();

    fireEvent.click(screen.getByText("记忆"));
    fireEvent.click(screen.getByText("主题"));
    await screen.findByText("部署流程.md");

    fireEvent.click(screen.getByLabelText("新建主题"));

    await waitFor(() =>
      expect(writeMemoryTopic).toHaveBeenCalledWith(
        "发布清单",
        "# 发布清单\n\n",
        null,
        "F1",
      ),
    );
    await waitFor(() =>
      expect(onOpen).toHaveBeenCalledWith(
        memoryTopicPath("F1", "发布清单"),
        "发布清单.md",
      ),
    );
  });

  it("shows project empty state with 新建 when there are no topics", async () => {
    renderProject();
    fireEvent.click(screen.getByText("记忆"));
    fireEvent.click(screen.getByText("主题"));
    expect(await screen.findByText("本项目还没有记忆")).toBeTruthy();
    expect(screen.getByText("新建")).toBeTruthy();
    expect(screen.getByLabelText("新建主题")).toBeTruthy();
  });

  it("forceOpen expands a collapsed project memory node", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <MemorySection
            scope={{ kind: "project", folderId: "F1", projectName: "项目甲" }}
            activePath={null}
            onOpen={vi.fn()}
            onTopicDeleted={vi.fn()}
            forceOpen
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    // Expanded → 画像 visible without clicking 记忆.
    expect(screen.getByText("画像")).toBeTruthy();
  });

  it("forceOpen is one-shot — user can collapse after reveal", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const onRevealApplied = vi.fn();
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <MemorySection
            scope={{ kind: "project", folderId: "F1", projectName: "项目甲" }}
            activePath={null}
            onOpen={vi.fn()}
            onTopicDeleted={vi.fn()}
            forceOpen
            onRevealApplied={onRevealApplied}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByText("画像")).toBeTruthy();
    expect(onRevealApplied).toHaveBeenCalled();

    // Host clears sticky reveal (forceOpen stays true briefly — one-shot must not re-open).
    fireEvent.click(screen.getByText("记忆"));
    expect(screen.queryByText("画像")).toBeNull();

    rerender(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <MemorySection
            scope={{ kind: "project", folderId: "F1", projectName: "项目甲" }}
            activePath={null}
            onOpen={vi.fn()}
            onTopicDeleted={vi.fn()}
            forceOpen
            onRevealApplied={onRevealApplied}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    // Still collapsed — sticky forceOpen must not re-expand.
    expect(screen.queryByText("画像")).toBeNull();
  });

  it("forceOpenTopics expands the 主题 sub-folder", async () => {
    vi.mocked(listMemoryTopics).mockResolvedValue(["部署流程"]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <MemorySection
            scope={{ kind: "project", folderId: "F1", projectName: "项目甲" }}
            activePath={memoryTopicPath("F1", "部署流程")}
            onOpen={vi.fn()}
            onTopicDeleted={vi.fn()}
            forceOpen
            forceOpenTopics
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByText("画像")).toBeTruthy();
    expect(await screen.findByText("部署流程.md")).toBeTruthy();
  });
});
