import { beforeEach, describe, expect, it, vi } from "vitest";

const showMock = vi.fn();
const notificationHandlers: Record<string, () => void> = {};

vi.mock("electron", () => ({
  Notification: class {
    static isSupported = () => true;
    on(event: string, cb: () => void) {
      notificationHandlers[event] = cb;
    }
    show = showMock;
  },
  BrowserWindow: {
    getFocusedWindow: () => ({
      isMinimized: () => false,
      restore: vi.fn(),
      focus: vi.fn(),
      webContents: { send: vi.fn() },
    }),
    getAllWindows: () => [],
  },
  ipcMain: { handle: vi.fn() },
}));

import { showOsNotification } from "../notification-service";

beforeEach(() => {
  showMock.mockClear();
  for (const k of Object.keys(notificationHandlers))
    delete notificationHandlers[k];
});

describe("showOsNotification", () => {
  it("shows a native notification", () => {
    const result = showOsNotification({
      title: "「测试」已完成",
      body: "点击查看",
      conversationId: "conv-1",
    });
    expect(result).toEqual({ ok: true });
    expect(showMock).toHaveBeenCalledTimes(1);
  });

  it("click sends conversationId to renderer", () => {
    showOsNotification({
      title: "需要审批",
      body: "",
      conversationId: "conv-2",
    });
    expect(notificationHandlers.click).toBeTypeOf("function");
    notificationHandlers.click();
  });
});
