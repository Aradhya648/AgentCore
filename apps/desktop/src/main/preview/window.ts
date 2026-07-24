/**
 * 预览宿主子窗口 —— 应用内「完整预览」的独立 BrowserWindow。
 *
 * 安全不变量（缺一不可）：
 * - 独立**非持久**分区（PREVIEW_PARTITION）——绝不触碰 defaultSession 的登录 cookie；
 * - sandbox:true、**无 preload**、nodeIntegration 关、contextIsolation 开；
 * - 该分区权限全拒（见 protocol.registerPreviewProtocol）；
 * - 顶级导航锁定 preview://；http/https 外链经既有安全校验转 shell.openExternal；
 *   window.open 同规则处理（安全外链转 shell，其余一律拒）。
 * - 同会话重复打开复用/聚焦既有窗口。
 */

import { BrowserWindow } from "electron";
import { lockPreviewNavigation } from "./navigation";
import { PREVIEW_PARTITION, buildPreviewUrl } from "./paths";
import { registerPreviewProtocol } from "./protocol";

/** conversationId → 该会话当前的预览窗口（复用/聚焦；关闭时清理）。 */
const previewWindows = new Map<string, BrowserWindow>();

/**
 * 打开（或复用聚焦）某会话工作区某文件的完整预览子窗口。同会话已有窗口 → 导航到新目标
 * 并聚焦；否则新建隔离子窗口。加载前确保协议处理器 + 权限锁已就位（幂等）。
 */
export function openPreviewWindow(conversationId: string, path: string): void {
  registerPreviewProtocol();
  const target = buildPreviewUrl(conversationId, path);

  const existing = previewWindows.get(conversationId);
  if (existing && !existing.isDestroyed()) {
    void existing.webContents.loadURL(target);
    if (existing.isMinimized()) existing.restore();
    existing.focus();
    return;
  }

  const win = new BrowserWindow({
    width: 1024,
    height: 768,
    minWidth: 400,
    minHeight: 300,
    title: "预览",
    autoHideMenuBar: true,
    webPreferences: {
      // 独立非持久分区：与 defaultSession（应用登录 cookie）完全隔离。
      partition: PREVIEW_PARTITION,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      // 刻意不挂 preload —— 预览页无需、也不该拿到任何应用 IPC 桥。
    },
  });
  previewWindows.set(conversationId, win);
  win.on("closed", () => {
    if (previewWindows.get(conversationId) === win) {
      previewWindows.delete(conversationId);
    }
  });

  lockPreviewNavigation(win.webContents);
  void win.webContents.loadURL(target);
}
