/**
 * 浏览器对话硬隔离：UI 缺 cid fail-closed、关对话幂等。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  BrowserWindow: {
    getFocusedWindow: () => null,
    getAllWindows: () => [],
  },
  WebContentsView: vi.fn(),
  session: {
    fromPartition: vi.fn(() => ({
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
      protocol: { handle: vi.fn() },
      on: vi.fn(),
    })),
  },
}));

import {
  closeAllLocalBrowserPages,
  closeConversationBrowserPages,
  listLocalBrowserConversationIdsForTests,
  navigateLocalBrowserPage,
  resetLegacyBrowserClearForTests,
  showLocalBrowserPage,
} from "../browser/host";

describe("Local browser conversation isolation (host fail-closed)", () => {
  beforeEach(() => {
    closeAllLocalBrowserPages();
    resetLegacyBrowserClearForTests();
  });

  it("show / navigate 缺 conversationId → 拒绝且不建页", () => {
    const win = {
      isDestroyed: () => false,
      contentView: { addChildView: vi.fn(), removeChildView: vi.fn() },
      once: vi.fn(),
      webContents: { send: vi.fn() },
    } as never;

    expect(
      showLocalBrowserPage(
        win,
        "page-1",
        { x: 0, y: 0, width: 100, height: 100 },
        "",
      ),
    ).toEqual({ ok: false, reason: "缺少 conversationId" });

    expect(
      navigateLocalBrowserPage("page-1", "https://example.com", ""),
    ).toEqual({
      ok: false,
      reason: "缺少 conversationId",
    });

    expect(listLocalBrowserConversationIdsForTests()).toEqual([]);
  });

  it("closeConversationBrowserPages 幂等", () => {
    expect(() => closeConversationBrowserPages("conv-x")).not.toThrow();
    expect(() => closeConversationBrowserPages("conv-x")).not.toThrow();
    expect(() => closeConversationBrowserPages("")).not.toThrow();
  });
});
