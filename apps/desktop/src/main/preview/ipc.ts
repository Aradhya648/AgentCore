/**
 * 预览的 IPC 注册（须在 app ready 后调用）。
 *
 * 装 `preview:open`（独立子窗口，保留）+ `preview:embed:*`（主窗口内嵌视图，主入口）句柄，并
 * 预注册协议处理器/权限锁（首帧前就位）。边界校验复用 ipc-validate 的薄守卫 + paths 的 bounds
 * 归一化——畸形入参（仅可能来自被攻破的 renderer）在边界即被拒。
 */

import {
  PREVIEW_CHANNELS,
  type PreviewEmbedResult,
  type PreviewOpenResult,
} from "@shared/preview-contract";
import { BrowserWindow, ipcMain } from "electron";
import { isRecord, requireStringFields } from "../ipc-validate";
import {
  closeEmbeddedPreview,
  goBackEmbeddedPreview,
  hideEmbeddedPreview,
  reloadEmbeddedPreview,
  setEmbeddedPreviewBounds,
  showEmbeddedPreview,
} from "./embed";
import { normalizePreviewBounds } from "./paths";
import { registerPreviewProtocol } from "./protocol";
import { openPreviewWindow } from "./window";

export function registerPreviewIpc(): void {
  // 协议处理器 + 权限锁提前就位（openPreviewWindow / showEmbeddedPreview 也会幂等再调）。
  registerPreviewProtocol();

  ipcMain.handle(
    PREVIEW_CHANNELS.open,
    async (_e, p: unknown): Promise<PreviewOpenResult> => {
      const args = requireStringFields(p, ["conversationId", "path"]);
      if (!args || !args.conversationId.trim() || !args.path.trim()) {
        return { ok: false, reason: "无效的请求参数" };
      }
      try {
        openPreviewWindow(args.conversationId, args.path);
        return { ok: true };
      } catch (e) {
        return {
          ok: false,
          reason: e instanceof Error ? e.message : "打开预览失败",
        };
      }
    },
  );

  ipcMain.handle(
    PREVIEW_CHANNELS.embedShow,
    async (e, p: unknown): Promise<PreviewEmbedResult> => {
      const args = requireStringFields(p, ["conversationId", "path"]);
      const bounds = normalizePreviewBounds(isRecord(p) ? p.bounds : null);
      if (
        !args ||
        !args.conversationId.trim() ||
        !args.path.trim() ||
        !bounds
      ) {
        return { ok: false, reason: "无效的请求参数" };
      }
      const win = BrowserWindow.fromWebContents(e.sender);
      if (!win) return { ok: false, reason: "无宿主窗口" };
      return showEmbeddedPreview(win, {
        conversationId: args.conversationId,
        path: args.path,
        bounds,
      });
    },
  );

  ipcMain.on(PREVIEW_CHANNELS.embedSetBounds, (_e, p: unknown) => {
    const bounds = normalizePreviewBounds(p);
    if (bounds) setEmbeddedPreviewBounds(bounds);
  });
  ipcMain.on(PREVIEW_CHANNELS.embedHide, () => hideEmbeddedPreview());
  ipcMain.on(PREVIEW_CHANNELS.embedReload, () => reloadEmbeddedPreview());
  ipcMain.on(PREVIEW_CHANNELS.embedBack, () => goBackEmbeddedPreview());
  ipcMain.on(PREVIEW_CHANNELS.embedClose, () => closeEmbeddedPreview());
}
