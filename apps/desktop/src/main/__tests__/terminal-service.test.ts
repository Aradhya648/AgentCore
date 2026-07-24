import { type Mock, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  dialog: { showMessageBox: vi.fn() },
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
  ipcMain: { handle: vi.fn() },
}));

vi.mock("node:child_process", () => ({
  spawn: vi.fn(() => {
    const handlers: Record<string, () => void> = {};
    return {
      on(event: string, cb: () => void) {
        handlers[event] = cb;
        if (event === "spawn") queueMicrotask(cb);
        return this;
      },
      unref: vi.fn(),
    };
  }),
}));

vi.mock("../fs-service", () => ({
  getStoredRoot: vi.fn(),
}));

import { dialog } from "electron";
import { getStoredRoot } from "../fs-service";
import { resetSessionRunAllowed } from "../fs/execGate";
import { confirmBashRun, openShellAtWorkspace } from "../terminal-service";

const showMessageBox = dialog.showMessageBox as unknown as Mock;
const getStoredRootMock = getStoredRoot as unknown as Mock;

beforeEach(() => {
  showMessageBox.mockReset();
  getStoredRootMock.mockReset();
  resetSessionRunAllowed();
});

describe("terminal-service.confirmBashRun", () => {
  it("默认取消（安全失败）", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    expect(await confirmBashRun("echo hi")).toBe(false);
    expect(showMessageBox.mock.calls.at(-1)?.[0].defaultId).toBe(0);
  });

  it("用户确认后放行（单次，不置本会话 flag）", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 1 });
    expect(await confirmBashRun("pnpm test")).toBe(true);
    const box = showMessageBox.mock.calls.at(-1)?.[0];
    expect(box.message).toContain("终端");
    expect(box.detail).toContain("pnpm test");
    expect(box.buttons).toEqual(["取消", "在终端运行", "本会话都允许"]);
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    expect(await confirmBashRun("echo again")).toBe(false);
    expect(showMessageBox).toHaveBeenCalledTimes(2);
  });

  it("本会话都允许后同进程跳过弹窗，且与 grantSessionRun / confirmExecute 共享 flag", async () => {
    const { confirmExecute, grantSessionRun } = await import("../fs/execGate");
    showMessageBox.mockResolvedValueOnce({ response: 2 });
    expect(await confirmBashRun("pnpm test")).toBe(true);
    expect(await confirmExecute({ code: "print(1)" })).toBe(true);
    expect(showMessageBox).toHaveBeenCalledTimes(1);
    resetSessionRunAllowed();
    grantSessionRun();
    expect(await confirmBashRun("echo via grant")).toBe(true);
    expect(showMessageBox).toHaveBeenCalledTimes(1);
  });

  it("长命令截断预览", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await confirmBashRun("x".repeat(3000));
    expect(showMessageBox.mock.calls.at(-1)?.[0].detail).toContain("已截断");
  });
});

describe("openShellAtWorkspace", () => {
  it("拒绝未授权根", async () => {
    getStoredRootMock.mockResolvedValueOnce(null);
    const r = await openShellAtWorkspace("missing");
    expect(r).toEqual({ ok: false, reason: "本地目录未授权或已移除" });
  });

  it("在有效工作区目录打开终端", async () => {
    getStoredRootMock.mockResolvedValueOnce({
      id: "r1",
      name: "Proj",
      absPath: "C:\\Proj",
    });
    const r = await openShellAtWorkspace("r1", "mini-claw");
    expect(r.ok).toBe(true);
  });
});
