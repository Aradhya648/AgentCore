// @vitest-environment jsdom

import type { BrowserApi } from "@shared/browser-contract";
import type { WorkspaceInfo } from "@/services/workspaces";
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 完整预览落点：断言 openInAppPreview → showBrowser + createPage + openWorkspaceHtml（不再 openPreview）。
const { showBrowser, createPage, openWorkspaceHtml } = vi.hoisted(() => ({
  showBrowser: vi.fn(),
  createPage: vi.fn(() => "browser-page:test"),
  openWorkspaceHtml: vi.fn().mockResolvedValue({ ok: true }),
}));

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
  useSidePanelStore: { getState: () => ({ showBrowser }) },
}));
vi.mock("@/stores/browserSessions", () => ({
  useBrowserSessionsStore: {
    getState: () => ({ createPage }),
  },
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
    vi.mocked(hasInAppPreview).mockReturnValue(true);
    vi.mocked(useConversationWorkspace).mockReturnValue(cloudWs);
    createPage.mockClear();
    createPage.mockReturnValue("browser-page:test");
    showBrowser.mockClear();
    openWorkspaceHtml.mockClear();
    openWorkspaceHtml.mockResolvedValue({ ok: true });
    (window as unknown as { fsApi?: unknown }).fsApi = {
      previewArchive: vi.fn(),
    };
    window.browserApi = {
      openWorkspaceHtml,
    } as unknown as BrowserApi;
  });

  afterEach(() => {
    vi.clearAllMocks();
    (window as unknown as { fsApi?: unknown }).fsApi = undefined;
    window.browserApi = undefined;
  });

  it("ws-id 寻址源（resolveWorkspaceSource 路径）也挂上「在浏览器打开」，且绑定 conversationId 而非 wsId", () => {
    const { result } = renderHook(() => useConversationFileSource("conv-123"));

    expect(result.current?.id).toBe("workspace:ws-XYZ");
    expect(typeof result.current?.openInBrowser).toBe("function");

    void result.current?.openInBrowser?.("dir/index.html");
    expect(openWorkspaceInBrowser).toHaveBeenCalledWith(
      "conv-123",
      "dir/index.html",
    );
  });

  it("同一 ws-id 源「完整预览」改道 BrowserPanel（showBrowser + openWorkspaceHtml，不 openPreview）", async () => {
    const { result } = renderHook(() => useConversationFileSource("conv-123"));

    expect(typeof result.current?.openInAppPreview).toBe("function");
    await result.current?.openInAppPreview?.("dir/app.html");

    expect(createPage).toHaveBeenCalledWith(
      expect.objectContaining({
        conversationId: "conv-123",
        title: "app.html",
        hostKind: "local",
      }),
    );
    expect(showBrowser).toHaveBeenCalled();
    expect(openWorkspaceHtml).toHaveBeenCalledWith({
      pageId: "browser-page:test",
      conversationId: "conv-123",
      path: "dir/app.html",
    });
  });

  it("web / 无对应能力时逐个门控：完整预览与在浏览器打开都不挂（入口不暴露）", () => {
    vi.mocked(hasInAppPreview).mockReturnValue(false);
    (window as unknown as { fsApi?: unknown }).fsApi = {}; // 无 previewArchive
    window.browserApi = undefined;

    const { result } = renderHook(() => useConversationFileSource("conv-123"));

    expect(result.current?.id).toBe("workspace:ws-XYZ");
    expect(result.current?.openInBrowser).toBeUndefined();
    expect(result.current?.openInAppPreview).toBeUndefined();
  });
});
