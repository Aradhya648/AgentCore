/**
 * 本机浏览器 IPC 注册（须在 app ready 后调用）。
 *
 * 装 `browser:*` 句柄；畸形入参 / 缺 conversationId 在边界拒（fail-closed）。
 * 不触碰 preview IPC / lockPreviewNavigation。
 *
 * show / hide 经同一串行队列，保证 detach 与 attach 顺序（无残影竞态）。
 */

import { BROWSER_CHANNELS, type BrowserResult } from "@shared/browser-contract";
import { isSafeExternalUrl } from "@shared/safe-url";
import { BrowserWindow, ipcMain, shell } from "electron";
import { isRecord, requireStringFields } from "../ipc-validate";
import {
  closeAllLocalBrowserPages,
  closeConversationBrowserPages,
  closeLocalBrowserPage,
  goBackLocalBrowserPage,
  goForwardLocalBrowserPage,
  hideLocalBrowserPages,
  navigateLocalBrowserPage,
  openLocalBrowserWorkspaceHtml,
  reloadLocalBrowserPage,
  setLocalBrowserBounds,
  showLocalBrowserPage,
} from "./host";
import { normalizeBrowserBounds } from "./paths";

/** show / hide 串行：后到的 op 等前一个结束（含 reject）再跑。 */
let attachmentOpQueue: Promise<unknown> = Promise.resolve();

function enqueueAttachmentOp<T>(fn: () => T | Promise<T>): Promise<T> {
  const run = attachmentOpQueue.then(fn, fn);
  attachmentOpQueue = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

export function registerBrowserIpc(): void {
  // 升级后清旧全局 partition 活页（幂等；无旧页则 no-op）。
  closeAllLocalBrowserPages();

  ipcMain.handle(
    BROWSER_CHANNELS.show,
    async (e, p: unknown): Promise<BrowserResult> =>
      enqueueAttachmentOp(() => {
        const args = requireStringFields(p, ["pageId", "conversationId"]);
        const bounds = normalizeBrowserBounds(isRecord(p) ? p.bounds : null);
        if (
          !args ||
          !args.pageId.trim() ||
          !args.conversationId.trim() ||
          !bounds
        ) {
          return { ok: false, reason: "无效的请求参数" };
        }
        const win = BrowserWindow.fromWebContents(e.sender);
        if (!win) return { ok: false, reason: "无宿主窗口" };
        return showLocalBrowserPage(
          win,
          args.pageId,
          bounds,
          args.conversationId,
        );
      }),
  );

  ipcMain.handle(BROWSER_CHANNELS.hide, async (): Promise<void> => {
    await enqueueAttachmentOp(() => {
      hideLocalBrowserPages();
    });
  });

  ipcMain.handle(
    BROWSER_CHANNELS.navigate,
    async (_e, p: unknown): Promise<BrowserResult> => {
      const args = requireStringFields(p, ["pageId", "conversationId", "url"]);
      if (
        !args ||
        !args.pageId.trim() ||
        !args.conversationId.trim() ||
        !args.url.trim()
      ) {
        return { ok: false, reason: "无效的请求参数" };
      }
      return navigateLocalBrowserPage(
        args.pageId,
        args.url,
        args.conversationId,
      );
    },
  );

  ipcMain.handle(
    BROWSER_CHANNELS.openWorkspaceHtml,
    async (_e, p: unknown): Promise<BrowserResult> => {
      const args = requireStringFields(p, ["pageId", "conversationId", "path"]);
      if (
        !args ||
        !args.pageId.trim() ||
        !args.conversationId.trim() ||
        !args.path.trim()
      ) {
        return { ok: false, reason: "无效的请求参数" };
      }
      return openLocalBrowserWorkspaceHtml(
        args.pageId,
        args.conversationId,
        args.path,
      );
    },
  );

  ipcMain.handle(
    BROWSER_CHANNELS.closeConversation,
    async (_e, p: unknown): Promise<BrowserResult> => {
      const args = requireStringFields(p, ["conversationId"]);
      if (!args || !args.conversationId.trim()) {
        return { ok: false, reason: "无效的请求参数" };
      }
      closeConversationBrowserPages(args.conversationId);
      return { ok: true };
    },
  );

  ipcMain.on(BROWSER_CHANNELS.setBounds, (_e, p: unknown) => {
    const bounds = normalizeBrowserBounds(p);
    if (bounds) setLocalBrowserBounds(bounds);
  });
  ipcMain.on(BROWSER_CHANNELS.reload, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) reloadLocalBrowserPage(args.pageId);
  });
  ipcMain.on(BROWSER_CHANNELS.back, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) goBackLocalBrowserPage(args.pageId);
  });
  ipcMain.on(BROWSER_CHANNELS.forward, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) goForwardLocalBrowserPage(args.pageId);
  });
  ipcMain.on(BROWSER_CHANNELS.close, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) closeLocalBrowserPage(args.pageId);
  });

  ipcMain.handle(
    BROWSER_CHANNELS.openExternal,
    async (_e, p: unknown): Promise<BrowserResult> => {
      const args = requireStringFields(p, ["url"]);
      const url = args?.url?.trim() ?? "";
      if (!url || !isSafeExternalUrl(url)) {
        return { ok: false, reason: "仅支持在系统浏览器打开 http(s) 链接" };
      }
      try {
        await shell.openExternal(url);
        return { ok: true };
      } catch (err) {
        return {
          ok: false,
          reason: err instanceof Error ? err.message : "无法打开系统浏览器",
        };
      }
    },
  );
}
