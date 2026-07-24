// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifyInfo: vi.fn(),
  notifyActionError: vi.fn(),
}));

import { handleTerminalResult, runTerminalBash } from "@/lib/terminalFeedback";
import { notifyError, notifyInfo } from "@/lib/toast";
import { useRunConfirmStore } from "@/stores/runConfirm";

const notifyErrorMock = vi.mocked(notifyError);
const notifyInfoMock = vi.mocked(notifyInfo);

beforeEach(() => {
  notifyErrorMock.mockReset();
  notifyInfoMock.mockReset();
  useRunConfirmStore.getState().reset();
});

describe("handleTerminalResult", () => {
  it("no-ops on success", () => {
    handleTerminalResult({ ok: true });
    expect(notifyErrorMock).not.toHaveBeenCalled();
    expect(notifyInfoMock).not.toHaveBeenCalled();
  });

  it("shows info toast on cancel", () => {
    handleTerminalResult({ ok: false, reason: "已取消" });
    expect(notifyInfoMock).toHaveBeenCalledWith("已取消");
  });

  it("shows error toast on failure", () => {
    handleTerminalResult({ ok: false, reason: "无法启动终端" });
    expect(notifyErrorMock).toHaveBeenCalledWith("无法启动终端");
  });
});

function mockTerminalApi(
  over?: Partial<{
    runBash: ReturnType<typeof vi.fn>;
    openShellAtRoot: ReturnType<typeof vi.fn>;
  }>,
) {
  return {
    runBash: vi.fn(async () => ({ ok: true as const })),
    openShellAtRoot: vi.fn(async () => ({ ok: true as const })),
    ...over,
  };
}

describe("runTerminalBash", () => {
  it("经 RunConfirm 后以 rendererConfirmed 调 terminalApi", async () => {
    const api = mockTerminalApi();
    window.terminalApi = api;
    const pending = runTerminalBash("pnpm test");
    // 微任务后 pending 卡应已挂上
    await Promise.resolve();
    expect(useRunConfirmStore.getState().pending?.command).toBe("pnpm test");
    useRunConfirmStore.getState().decide("run");
    await pending;
    expect(api.runBash).toHaveBeenCalledWith({
      command: "pnpm test",
      rendererConfirmed: true,
    });
    window.terminalApi = undefined;
  });

  it("用户取消 → info toast，不调 runBash", async () => {
    const api = mockTerminalApi();
    window.terminalApi = api;
    const pending = runTerminalBash("rm -rf /");
    await Promise.resolve();
    useRunConfirmStore.getState().decide("cancel");
    await pending;
    expect(api.runBash).not.toHaveBeenCalled();
    expect(notifyInfoMock).toHaveBeenCalledWith("已取消在终端运行");
    window.terminalApi = undefined;
  });

  it("本会话已放行 → 直跑，不挂卡", async () => {
    useRunConfirmStore.getState().markSessionAllowed();
    const api = mockTerminalApi();
    window.terminalApi = api;
    await runTerminalBash("echo ok");
    expect(useRunConfirmStore.getState().pending).toBeNull();
    expect(api.runBash).toHaveBeenCalledWith({
      command: "echo ok",
      rendererConfirmed: true,
    });
    window.terminalApi = undefined;
  });
});
