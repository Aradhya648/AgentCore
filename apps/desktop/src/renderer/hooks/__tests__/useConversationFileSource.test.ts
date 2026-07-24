// @vitest-environment jsdom

import type { WorkspaceInfo } from "@/services/workspaces";
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 内置浏览器 tab（完整预览）的落点：断言 openInAppPreview 路由到会话作用域的 openPreview。
const { openPreview } = vi.hoisted(() => ({ openPreview: vi.fn() }));

// 只桩掉会拉 react-query / 真实服务的邻居；workspaceSource 用真的（接缝正是它 + 本 hook 的拼接）。
vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => [],
  getConversations: () => [],
}));
vi.mock("@/hooks/useFolders", () => ({ useFolders: () => [] }));
vi.mock("@/hooks/useWorkspaces", () => ({ useConversationWorkspace: vi.fn() }));
vi.mock("@/services/sidecarRouting", () => ({
  resolveConversationLocalTarget: vi.fn(),
}));
vi.mock("@/lib/capabilities", () => ({
  hasInAppPreview: vi.fn(() => true),
  hasLocalFiles: vi.fn(() => false),
}));
vi.mock("@/services/workspace", () => ({
  openWorkspaceInBrowser: vi.fn(),
}));
vi.mock("@/stores/sidePanel", () => ({
  useSidePanelStore: { getState: () => ({ openPreview }) },
}));

import { useConversationFileSource } from "@/hooks/useConversationFileSource";
import { useConversationWorkspace } from "@/hooks/useWorkspaces";
import { hasInAppPreview } from "@/lib/capabilities";
import { openWorkspaceInBrowser } from "@/services/workspace";

const cloudWs: WorkspaceInfo = {
  wsId: "ws-XYZ",
  name: "工作区",
  location: "cloud",
  rootId: null,
  subpath: "",
  hasFiles: true,
};

describe("useConversationFileSource — 对话侧栏云端源的完整预览出口（接缝）", () => {
  beforeEach(() => {
    vi.mocked(useConversationWorkspace).mockReturnValue(cloudWs);
    vi.mocked(hasInAppPreview).mockReturnValue(true);
    // 「在浏览器打开」依赖 previewArchive（桌面外壳专属）。
    (window as unknown as { fsApi?: unknown }).fsApi = {
      previewArchive: vi.fn(),
    };
  });

  afterEach(() => {
    vi.clearAllMocks();
    (window as unknown as { fsApi?: unknown }).fsApi = undefined;
  });

  it("ws-id 寻址源（resolveWorkspaceSource 路径）也挂上「在浏览器打开」，且绑定 conversationId 而非 wsId", () => {
    const { result } = renderHook(() => useConversationFileSource("conv-123"));

    // 走的正是 /v1/workspaces 列出后的 ws-id 源（回归的接缝入口）。
    expect(result.current?.id).toBe("workspace:ws-XYZ");
    expect(typeof result.current?.openInBrowser).toBe("function");

    void result.current?.openInBrowser?.("dir/index.html");
    // 关键断言：会话作用域寻址（conv-123），不是 wsId —— 否则会快照错工作区。
    expect(openWorkspaceInBrowser).toHaveBeenCalledWith(
      "conv-123",
      "dir/index.html",
    );
  });

  it("同一 ws-id 源也挂上「完整预览」，路由到会话作用域的预览 tab", () => {
    const { result } = renderHook(() => useConversationFileSource("conv-123"));

    expect(typeof result.current?.openInAppPreview).toBe("function");
    void result.current?.openInAppPreview?.("dir/app.html");
    expect(openPreview).toHaveBeenCalledWith(
      "conv-123",
      "dir/app.html",
      "app.html",
    );
  });

  it("web / 无对应能力时逐个门控：完整预览与在浏览器打开都不挂（入口不暴露）", () => {
    vi.mocked(hasInAppPreview).mockReturnValue(false);
    (window as unknown as { fsApi?: unknown }).fsApi = {}; // 无 previewArchive

    const { result } = renderHook(() => useConversationFileSource("conv-123"));

    expect(result.current?.id).toBe("workspace:ws-XYZ");
    expect(result.current?.openInBrowser).toBeUndefined();
    expect(result.current?.openInAppPreview).toBeUndefined();
  });
});
