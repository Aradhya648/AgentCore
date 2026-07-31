/**
 * Local 浏览器 Attachment：hide=脱离、过期 show 拒、ensurePageKind 不因 wasActive 复活。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  BrowserWindow: {
    getFocusedWindow: () => null,
    getAllWindows: () => [],
  },
  WebContentsView: vi.fn().mockImplementation(() => ({
    webContents: {
      isDestroyed: () => false,
      on: vi.fn(),
      loadURL: vi.fn().mockResolvedValue(undefined),
      getURL: () => "about:blank",
      getTitle: () => "",
      navigationHistory: {
        canGoBack: () => false,
        canGoForward: () => false,
      },
      close: vi.fn(),
      isLoadingMainFrame: () => false,
      reload: vi.fn(),
      setWindowOpenHandler: vi.fn(),
    },
    setVisible: vi.fn(),
    setBounds: vi.fn(),
    getBounds: () => ({ x: 0, y: 0, width: 100, height: 100 }),
  })),
  session: {
    fromPartition: vi.fn(() => ({
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
      protocol: { handle: vi.fn(), isProtocolHandled: () => false },
      on: vi.fn(),
    })),
  },
  shell: { openExternal: vi.fn() },
}));

vi.mock("../browser/workspace-protocol", () => ({
  registerWorkspaceProtocolFor: vi.fn(),
}));

import {
  advanceAttachmentGenerationForTests,
  closeAllLocalBrowserPages,
  hideLocalBrowserPages,
  localBrowserActivePageIdForTests,
  localBrowserAttachmentGenerationForTests,
  localBrowserPageVisibleForTests,
  navigateLocalBrowserPage,
  resetLegacyBrowserClearForTests,
  setBeforeAttachCheckForTests,
  showLocalBrowserPage,
} from "../browser/host";

const BOUNDS = { x: 10, y: 20, width: 400, height: 300 };

function mockWin() {
  return {
    isDestroyed: () => false,
    contentView: { addChildView: vi.fn(), removeChildView: vi.fn() },
    once: vi.fn(),
    webContents: { send: vi.fn() },
  } as never;
}

describe("Local browser Attachment", () => {
  beforeEach(() => {
    closeAllLocalBrowserPages();
    resetLegacyBrowserClearForTests();
    setBeforeAttachCheckForTests(null);
  });

  it("hide 清 active 且视图不可见", () => {
    const win = mockWin();
    expect(showLocalBrowserPage(win, "page-1", BOUNDS, "conv-1")).toEqual({
      ok: true,
      url: "about:blank",
      title: "",
      canGoBack: false,
      canGoForward: false,
    });
    expect(localBrowserActivePageIdForTests()).toBe("page-1");
    expect(localBrowserPageVisibleForTests("page-1")).toBe(true);

    const genBefore = localBrowserAttachmentGenerationForTests();
    hideLocalBrowserPages();
    expect(localBrowserActivePageIdForTests()).toBeNull();
    expect(localBrowserPageVisibleForTests("page-1")).toBe(false);
    expect(localBrowserAttachmentGenerationForTests()).toBeGreaterThan(
      genBefore,
    );
  });

  it("hide 后再 show 才可见", () => {
    const win = mockWin();
    showLocalBrowserPage(win, "page-1", BOUNDS, "conv-1");
    hideLocalBrowserPages();
    expect(localBrowserPageVisibleForTests("page-1")).toBe(false);
    expect(localBrowserActivePageIdForTests()).toBeNull();

    expect(showLocalBrowserPage(win, "page-1", BOUNDS, "conv-1")).toEqual({
      ok: true,
      url: "about:blank",
      title: "",
      canGoBack: false,
      canGoForward: false,
    });
    expect(localBrowserActivePageIdForTests()).toBe("page-1");
    expect(localBrowserPageVisibleForTests("page-1")).toBe(true);
  });

  it("ensurePageKind 在 detached 时不点亮（非 hide 后 wasActive 复活）", () => {
    const win = mockWin();
    showLocalBrowserPage(win, "page-1", BOUNDS, "conv-1");
    hideLocalBrowserPages();
    expect(localBrowserActivePageIdForTests()).toBeNull();
    expect(localBrowserPageVisibleForTests("page-1")).toBe(false);

    // 换 kind → ensurePageKind 销毁重建；已脱离则不得 setVisible(true)
    expect(
      navigateLocalBrowserPage(
        "page-1",
        "workspace://conv-1/site/index.html",
        "conv-1",
      ),
    ).toEqual({ ok: true });
    expect(localBrowserActivePageIdForTests()).toBeNull();
    expect(localBrowserPageVisibleForTests("page-1")).toBe(false);
  });

  it("过期 show（generation 已 bump）拒", () => {
    const win = mockWin();
    setBeforeAttachCheckForTests(() => {
      advanceAttachmentGenerationForTests();
    });
    expect(showLocalBrowserPage(win, "page-stale", BOUNDS, "conv-1")).toEqual({
      ok: false,
      reason: "attachment_stale",
    });
    expect(localBrowserActivePageIdForTests()).toBeNull();
    expect(localBrowserPageVisibleForTests("page-stale")).toBe(false);
  });
});
