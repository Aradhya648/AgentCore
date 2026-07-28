/**
 * 本机浏览器 IPC 注册（须在 app ready 后调用）。
 *
 * 装 `browser:*` 句柄；畸形入参在边界拒。不触碰 preview IPC / lockPreviewNavigation。
 */

import { BROWSER_CHANNELS, type BrowserResult } from "@shared/browser-contract";
import { BrowserWindow, ipcMain } from "electron";
import { isRecord, requireStringFields } from "../ipc-validate";
import {
  closeLocalBrowserPage,
  goBackLocalBrowserPage,
  hideLocalBrowserPages,
  navigateLocalBrowserPage,
  openLocalBrowserWorkspaceHtml,
  reloadLocalBrowserPage,
  setLocalBrowserBounds,
  showLocalBrowserPage,
} from "./host";
import { normalizeBrowserBounds } from "./paths";
import { registerWorkspaceProtocol } from "./workspace-protocol";

export function registerBrowserIpc(): void {
  // 工作区协议尽早就位（openWorkspaceHtml / 相对资源导航前幂等再调）。
  registerWorkspaceProtocol();

  ipcMain.handle(
    BROWSER_CHANNELS.show,
    async (e, p: unknown): Promise<BrowserResult> => {
      const args = requireStringFields(p, ["pageId"]);
      const bounds = normalizeBrowserBounds(isRecord(p) ? p.bounds : null);
      if (!args || !args.pageId.trim() || !bounds) {
        return { ok: false, reason: "无效的请求参数" };
      }
      const win = BrowserWindow.fromWebContents(e.sender);
      if (!win) return { ok: false, reason: "无宿主窗口" };
      return showLocalBrowserPage(win, args.pageId, bounds);
    },
  );

  ipcMain.handle(
    BROWSER_CHANNELS.navigate,
    async (_e, p: unknown): Promise<BrowserResult> => {
      const args = requireStringFields(p, ["pageId", "url"]);
      if (!args || !args.pageId.trim() || !args.url.trim()) {
        return { ok: false, reason: "无效的请求参数" };
      }
      return navigateLocalBrowserPage(args.pageId, args.url);
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

  ipcMain.on(BROWSER_CHANNELS.setBounds, (_e, p: unknown) => {
    const bounds = normalizeBrowserBounds(p);
    if (bounds) setLocalBrowserBounds(bounds);
  });
  ipcMain.on(BROWSER_CHANNELS.hide, () => hideLocalBrowserPages());
  ipcMain.on(BROWSER_CHANNELS.reload, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) reloadLocalBrowserPage(args.pageId);
  });
  ipcMain.on(BROWSER_CHANNELS.back, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) goBackLocalBrowserPage(args.pageId);
  });
  ipcMain.on(BROWSER_CHANNELS.close, (_e, p: unknown) => {
    const args = requireStringFields(p, ["pageId"]);
    if (args?.pageId) closeLocalBrowserPage(args.pageId);
  });
}
