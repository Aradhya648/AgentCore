import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", async () => {
  // async 工厂：用 await import 取 os，避免引用 hoist 之外的顶层 import。
  const { tmpdir } = await import("node:os");
  return {
    BrowserWindow: {
      getFocusedWindow: () => null,
      getAllWindows: () => [],
    },
    dialog: {
      showSaveDialog: vi.fn(),
    },
    app: {
      getPath: () => tmpdir(),
    },
  };
});

import { dialog } from "electron";
import { sanitizeFilename, saveBytesToDisk } from "../fs/save";

const showSaveDialog = dialog.showSaveDialog as unknown as ReturnType<
  typeof vi.fn
>;

describe("sanitizeFilename", () => {
  it("剥掉路径分隔符与前导点（防目录穿越进 defaultPath）", () => {
    const out = sanitizeFilename("../../etc/passwd");
    expect(out).not.toMatch(/[/\\]/);
    expect(out.startsWith(".")).toBe(false);
  });

  it("替换 Windows 保留字符与控制字符", () => {
    expect(sanitizeFilename('a<b>:"c|d?e*.txt')).toBe("a_b___c_d_e_.txt");
    expect(sanitizeFilename("a\u0000b\u001f.txt")).toBe("a_b_.txt");
  });

  it("去掉结尾点/空格（Windows 不接受）", () => {
    expect(sanitizeFilename("report. ")).toBe("report");
  });

  it("空名/纯点回退 download，中文名保留", () => {
    expect(sanitizeFilename("")).toBe("download");
    expect(sanitizeFilename("...")).toBe("download");
    expect(sanitizeFilename("报告 v2.xlsx")).toBe("报告 v2.xlsx");
  });

  it("超长截断到 150 字符", () => {
    expect(sanitizeFilename("x".repeat(300)).length).toBe(150);
  });
});

describe("saveBytesToDisk", () => {
  let destDir: string;

  beforeEach(async () => {
    destDir = await fs.mkdtemp(join(tmpdir(), "ac-save-"));
    showSaveDialog.mockReset();
  });

  afterEach(async () => {
    await fs.rm(destDir, { recursive: true, force: true });
  });

  it("写入用户选定路径，回实际文件名，不留临时文件", async () => {
    const target = join(destDir, "renamed.bin");
    showSaveDialog.mockResolvedValue({ canceled: false, filePath: target });
    const bytes = new Uint8Array([1, 2, 3, 250]);

    const result = await saveBytesToDisk("suggested.bin", bytes);

    expect(result).toEqual({ ok: true, fileName: "renamed.bin" });
    expect(new Uint8Array(await fs.readFile(target))).toEqual(bytes);
    expect(await fs.readdir(destDir)).toEqual(["renamed.bin"]);
  });

  it("对话框 defaultPath 用净化后的文件名预填", async () => {
    showSaveDialog.mockResolvedValue({ canceled: true, filePath: undefined });

    await saveBytesToDisk("../evil<:>.bin", new Uint8Array([1]));

    const options = showSaveDialog.mock.calls[0][0] as {
      defaultPath: string;
    };
    const base = options.defaultPath.split(/[/\\]/).pop() ?? "";
    expect(base).not.toMatch(/[<>:"|?*]/);
    expect(base.startsWith(".")).toBe(false);
  });

  it("用户取消 → cancelled（非错误），不写任何文件", async () => {
    showSaveDialog.mockResolvedValue({ canceled: true, filePath: undefined });

    const result = await saveBytesToDisk("a.bin", new Uint8Array([1]));

    expect(result).toEqual({ ok: false, reason: "cancelled" });
    expect(await fs.readdir(destDir)).toEqual([]);
  });

  it("写盘失败 → error 结果，目标与临时文件都不残留", async () => {
    const target = join(destDir, "no-such-dir", "out.bin");
    showSaveDialog.mockResolvedValue({ canceled: false, filePath: target });

    const result = await saveBytesToDisk("out.bin", new Uint8Array([1]));

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("error");
    expect(await fs.readdir(destDir)).toEqual([]);
  });
});
