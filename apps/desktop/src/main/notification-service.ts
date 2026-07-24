/**
 * 桌面 OS 原生通知 —— 跨对话协作感知在窗口失焦时的系统栏出口。
 *
 * Renderer 无法伪造：通知由主进程 `Notification` 弹出；点击聚焦窗口并可选带回
 * `conversationId` 供 renderer 跳转。
 */
import {
  NOTIFICATION_CHANNELS,
  type NotificationShowInput,
  type NotificationShowResult,
} from "@shared/notification-contract";
import { BrowserWindow, Notification, ipcMain } from "electron";

function focusMainWindow(): BrowserWindow | null {
  const win =
    BrowserWindow.getFocusedWindow() ??
    BrowserWindow.getAllWindows()[0] ??
    null;
  if (!win) return null;
  if (win.isMinimized()) win.restore();
  win.focus();
  return win;
}

function parseInput(raw: unknown): NotificationShowInput | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const title = typeof o.title === "string" ? o.title.trim() : "";
  const body = typeof o.body === "string" ? o.body.trim() : "";
  if (!title) return null;
  const conversationId =
    typeof o.conversationId === "string" && o.conversationId.trim()
      ? o.conversationId.trim()
      : undefined;
  return { title, body, conversationId };
}

/** 在用户 shell 通知中心弹出一条原生通知。 */
export function showOsNotification(
  input: NotificationShowInput,
): NotificationShowResult {
  if (!Notification.isSupported()) {
    return { ok: false, reason: "系统不支持原生通知" };
  }
  const notification = new Notification({
    title: input.title,
    body: input.body,
  });
  notification.on("click", () => {
    const win = focusMainWindow();
    if (win && input.conversationId) {
      win.webContents.send(NOTIFICATION_CHANNELS.clicked, {
        conversationId: input.conversationId,
      });
    }
  });
  notification.show();
  return { ok: true };
}

export function registerNotificationIpc(): void {
  ipcMain.handle(
    NOTIFICATION_CHANNELS.show,
    (_event, raw: unknown): NotificationShowResult => {
      const input = parseInput(raw);
      if (!input) return { ok: false, reason: "无效通知参数" };
      return showOsNotification(input);
    },
  );
}
