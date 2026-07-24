// @vitest-environment jsdom

// saveBlob 是所有下载（云工作区文件 / 快照 zip / 对话导出 / IM 附件 / 图表·白板导出）
// 汇聚的唯一落盘接缝：桌面走 fs:saveFile IPC（Electron 不支持 <a download>+blob:，
// blob: 导航还会被 will-navigate 守卫拦截），web 走 anchor + 延迟 revoke。
// 两条分支 + 取消/失败语义都在这里钉住。
import type { SaveFileResult } from "@shared/ipc-contract";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { saveBlob } from "@/services/workspaceHttp";

type ClickCapture = {
  href: string;
  download: string;
  connectedAtClick: boolean;
};

function installFsApi(result: SaveFileResult) {
  const saveFile = vi.fn().mockResolvedValue(result);
  window.__WEB__ = undefined;
  window.fsApi = { saveFile } as unknown as typeof window.fsApi;
  return saveFile;
}

let clickSpy: ReturnType<typeof vi.spyOn>;
let clicks: ClickCapture[];
let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clicks = [];
  clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push({
        href: this.href,
        download: this.download,
        connectedAtClick: this.isConnected,
      });
    });
  // jsdom 不实现 createObjectURL/revokeObjectURL —— 桩成稳定串。
  createObjectURL = vi.fn(() => "blob:jsdom/fake-1");
  revokeObjectURL = vi.fn();
  URL.createObjectURL =
    createObjectURL as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL =
    revokeObjectURL as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  clickSpy.mockRestore();
  vi.useRealTimers();
  window.__WEB__ = undefined;
  // @ts-expect-error 测试后还原为「无 preload」环境
  window.fsApi = undefined;
});

describe("saveBlob · 桌面（fs:saveFile IPC）", () => {
  it("把字节与文件名交主进程，成功即 resolve、不走 anchor", async () => {
    const saveFile = installFsApi({ ok: true, fileName: "a.bin" });

    await saveBlob(new Blob([new Uint8Array([1, 2, 250])]), "a.bin");

    expect(saveFile).toHaveBeenCalledTimes(1);
    const [name, bytes] = saveFile.mock.calls[0] as [string, Uint8Array];
    expect(name).toBe("a.bin");
    expect(Array.from(bytes)).toEqual([1, 2, 250]);
    expect(clickSpy).not.toHaveBeenCalled();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("空文件名回退 download", async () => {
    const saveFile = installFsApi({ ok: true, fileName: "download" });

    await saveBlob(new Blob(["x"]), "");

    expect(saveFile.mock.calls[0][0]).toBe("download");
  });

  it("用户在保存对话框取消 → 正常 resolve（主动放弃非错误）", async () => {
    installFsApi({ ok: false, reason: "cancelled" });

    await expect(saveBlob(new Blob(["x"]), "a.bin")).resolves.toBeUndefined();
  });

  it("主进程写盘失败 → reject 携错误信息（供入口 toast）", async () => {
    installFsApi({ ok: false, reason: "error", message: "磁盘已满" });

    await expect(saveBlob(new Blob(["x"]), "a.bin")).rejects.toThrow(
      "磁盘已满",
    );
  });
});

describe("saveBlob · web（anchor + 延迟 revoke）", () => {
  beforeEach(() => {
    // 生产 web 客户端：browserStubs 装了 fsApi 桩并置 __WEB__ → 必须走 anchor 而非桩。
    window.__WEB__ = true;
    window.fsApi = {
      saveFile: vi.fn(),
    } as unknown as typeof window.fsApi;
  });

  it("经 <a download> 触发下载，click 时 anchor 在文档中、事后移除", async () => {
    await saveBlob(new Blob(["hello"]), "h.txt");

    expect(window.fsApi.saveFile).not.toHaveBeenCalled();
    expect(clicks).toHaveLength(1);
    expect(clicks[0].href).toBe("blob:jsdom/fake-1");
    expect(clicks[0].download).toBe("h.txt");
    expect(clicks[0].connectedAtClick).toBe(true);
    expect(document.querySelector("a")).toBeNull();
  });

  it("revoke 延迟到下载启动之后（click 后同步 revoke 属规范竞态）", async () => {
    vi.useFakeTimers();

    await saveBlob(new Blob(["hello"]), "h.txt");

    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60_000);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:jsdom/fake-1");
  });
});
