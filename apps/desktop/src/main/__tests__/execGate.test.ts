import { type Mock, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  dialog: { showMessageBox: vi.fn() },
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
}));

import { dialog } from "electron";
import {
  confirmExecute,
  confirmOpenPath,
  grantSessionRun,
  isSessionRunAllowed,
  requiresOpenConfirm,
  resetSessionRunAllowed,
} from "../fs/execGate";

const showMessageBox = dialog.showMessageBox as unknown as Mock;

beforeEach(() => {
  showMessageBox.mockReset();
  resetSessionRunAllowed();
});

describe("execGate.requiresOpenConfirm（IPC-002 白名单姿态）", () => {
  it("已知安全类型（文档/媒体/图片/文本/压缩包）→ 直开、不弹确认", () => {
    for (const p of [
      "a.txt",
      "b.pdf",
      "c.png",
      "d.docx",
      "e.json",
      "f.md",
      "g.csv",
      "h.mp4",
      "i.svg",
      "archive.tar.gz",
      "x/y/report.xlsx",
      "deep\\sub\\photo.JPEG",
    ]) {
      expect(requiresOpenConfirm(p)).toBe(false);
    }
  });

  it("可执行 / 脚本 / 宏文档 / 未知类型 → 一律需确认", () => {
    for (const p of [
      "a.bat",
      "a.CMD",
      "x/y.exe",
      "deep\\sub\\run.EXE",
      "s.ps1",
      "t.sh",
      "i.js",
      "v.vbs",
      "z.jar",
      "w.msi",
      "h.hta",
      "p.py",
      "macro.docm",
      "sheet.xlsm",
      "weird.unknownext",
    ]) {
      expect(requiresOpenConfirm(p)).toBe(true);
    }
  });

  it("E1 黑名单缺口：Windows LOLBin 类型也需确认（白名单天然覆盖）", () => {
    for (const p of [
      "x.diagcab",
      "y.appref-ms",
      "z.settingcontent-ms",
      "h.chm",
      "g.application",
      "k.gadget",
    ]) {
      expect(requiresOpenConfirm(p)).toBe(true);
    }
  });

  it("E2 文件名归一化：末尾点 / 空格不再骗过分类", () => {
    expect(requiresOpenConfirm("evil.exe.")).toBe(true);
    expect(requiresOpenConfirm("evil.exe ")).toBe(true);
    expect(requiresOpenConfirm("evil.exe...  ")).toBe(true);
    // 安全类型即使末尾带点 / 空格，规整后仍判为安全
    expect(requiresOpenConfirm("notes.txt.")).toBe(false);
    expect(requiresOpenConfirm("a.pdf ")).toBe(false);
  });

  it("无扩展名 / dotfile / 目录末尾分隔 → 需确认（无法判定安全）", () => {
    expect(requiresOpenConfirm("Makefile")).toBe(true);
    expect(requiresOpenConfirm(".bashrc")).toBe(true);
    expect(requiresOpenConfirm("dir/sub/")).toBe(true);
    expect(requiresOpenConfirm("noext")).toBe(true);
  });
});

describe("execGate.grantSessionRun", () => {
  it("置位后 isSessionRunAllowed 为 true", () => {
    expect(isSessionRunAllowed()).toBe(false);
    grantSessionRun();
    expect(isSessionRunAllowed()).toBe(true);
  });
});

describe("execGate 确认对话框（native 兜底；非 workspaceOp execute 路径）", () => {
  it("confirmExecute：用户取消（response 0）→ false，且默认 / 取消按钮均为取消位", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await expect(
      confirmExecute({ language: "python", code: "print(1)" }),
    ).resolves.toBe(false);
    const box = showMessageBox.mock.calls.at(-1)?.[0];
    expect(box.defaultId).toBe(0);
    expect(box.cancelId).toBe(0);
    expect(box.type).toBe("warning");
    expect(box.buttons).toEqual(["取消", "运行", "本会话都允许"]);
    expect(box.message).toContain("python");
    expect(box.detail).toContain("print(1)");
  });

  it("confirmExecute：仅「运行」（response 1）→ true，不置本会话 flag", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 1 });
    await expect(confirmExecute({ code: "x" })).resolves.toBe(true);
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await expect(confirmExecute({ code: "y" })).resolves.toBe(false);
    expect(showMessageBox).toHaveBeenCalledTimes(2);
  });

  it("confirmExecute：「本会话都允许」（response 2）→ true，后续同进程跳过弹窗", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 2 });
    await expect(confirmExecute({ code: "x" })).resolves.toBe(true);
    await expect(confirmExecute({ code: "y" })).resolves.toBe(true);
    expect(showMessageBox).toHaveBeenCalledTimes(1);
  });

  it("E3：stdin 存在时确认框必须展示其内容（隐藏输入不再泄漏）", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await confirmExecute({
      language: "python",
      code: "exec(sys.stdin.read())",
      stdin: "import os; os.system('calc')",
    });
    const detail = showMessageBox.mock.calls.at(-1)?.[0].detail as string;
    expect(detail).toContain("stdin");
    expect(detail).toContain("os.system('calc')");
    expect(detail).toContain("exec(sys.stdin.read())");
  });

  it("E3：无 stdin 时不显示 stdin 段（不给常规执行添噪）", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await confirmExecute({ language: "python", code: "print(1)" });
    expect(showMessageBox.mock.calls.at(-1)?.[0].detail).not.toContain("stdin");
  });

  it("E3：超长 stdin 被截断（不撑爆对话框）", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await confirmExecute({ code: "x", stdin: "A".repeat(5000) });
    expect(showMessageBox.mock.calls.at(-1)?.[0].detail).toContain("已截断");
  });

  it("confirmOpenPath：仍为两按钮，response→boolean 映射，detail 含文件名", async () => {
    showMessageBox.mockResolvedValueOnce({ response: 1 });
    await expect(confirmOpenPath("tools/run.bat")).resolves.toBe(true);
    const box = showMessageBox.mock.calls.at(-1)?.[0];
    expect(box.buttons).toEqual(["取消", "打开"]);
    expect(box.detail).toContain("run.bat");

    showMessageBox.mockResolvedValueOnce({ response: 0 });
    await expect(confirmOpenPath("tools/run.bat")).resolves.toBe(false);
  });
});
