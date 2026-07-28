// @vitest-environment jsdom

import type { BrowserApi } from "@shared/browser-contract";
import { afterEach, describe, expect, it, vi } from "vitest";

// 侧邻模块只在 resolve* 分支用到，这里只测 createWorkspaceSource 门控 → 桩掉即可（避免拉 react-query）。
vi.mock("@/hooks/useConversations", () => ({
  getConversations: vi.fn(() => []),
}));
vi.mock("@/services/sidecarRouting", () => ({
  resolveConversationLocalTarget: vi.fn(),
}));

const { showBrowser, createPage } = vi.hoisted(() => ({
  showBrowser: vi.fn(),
  createPage: vi.fn(() => "page-1"),
}));

vi.mock("@/stores/sidePanel", () => ({
  useSidePanelStore: { getState: () => ({ showBrowser }) },
}));
vi.mock("@/stores/browserSessions", () => ({
  useBrowserSessionsStore: { getState: () => ({ createPage }) },
}));

import { createWorkspaceSource } from "@/services/sources/workspaceSource";

describe("createWorkspaceSource — 应用内「完整预览」入口门控（Browser）", () => {
  afterEach(() => {
    window.browserApi = undefined;
    showBrowser.mockClear();
    createPage.mockClear();
  });

  it("桌面：browserApi.openWorkspaceHtml 存在 → 挂 openInAppPreview 并改道 BrowserPanel", async () => {
    const openWorkspaceHtml = vi.fn().mockResolvedValue({ ok: true });
    window.browserApi = {
      openWorkspaceHtml,
    } as unknown as BrowserApi;

    const source = createWorkspaceSource("c1", "工作区");
    expect(typeof source.openInAppPreview).toBe("function");

    await source.openInAppPreview?.("dir/index.html");
    expect(showBrowser).toHaveBeenCalledOnce();
    expect(createPage).toHaveBeenCalledWith(
      expect.objectContaining({
        conversationId: "c1",
        hostKind: "local",
      }),
    );
    expect(openWorkspaceHtml).toHaveBeenCalledWith({
      pageId: "page-1",
      conversationId: "c1",
      path: "dir/index.html",
    });
  });

  it("失败结果（ok:false）→ 抛出 reason 供 UI toast", async () => {
    const openWorkspaceHtml = vi
      .fn()
      .mockResolvedValue({ ok: false, reason: "打不开" });
    window.browserApi = {
      openWorkspaceHtml,
    } as unknown as BrowserApi;

    const source = createWorkspaceSource("c1");
    await expect(source.openInAppPreview?.("index.html")).rejects.toThrow(
      "打不开",
    );
  });

  it("web：无 browserApi.openWorkspaceHtml → 不挂 openInAppPreview（入口不暴露）", () => {
    const source = createWorkspaceSource("c1");
    expect(source.openInAppPreview).toBeUndefined();
  });
});
