import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import JSZip from "jszip";
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
      showOpenDialog: vi.fn(),
    },
    shell: {
      openPath: vi.fn().mockResolvedValue(""),
    },
    app: {
      getPath: () => tmpdir(),
    },
  };
});

import { dialog, shell } from "electron";
import { checkoutArchive, previewArchive, safeJoinUnder } from "../fs/checkout";

const showOpenDialog = dialog.showOpenDialog as unknown as ReturnType<
  typeof vi.fn
>;

describe("safeJoinUnder", () => {
  const dest = join(tmpdir(), "ac-safe-root");

  it("allows nested relative paths", () => {
    expect(safeJoinUnder(dest, "a/b.txt")).toBe(join(dest, "a", "b.txt"));
  });

  it("rejects .. segments", () => {
    expect(safeJoinUnder(dest, "../escape.txt")).toBeNull();
    expect(safeJoinUnder(dest, "a/../../escape.txt")).toBeNull();
  });

  it("rejects null bytes", () => {
    expect(safeJoinUnder(dest, "a\0b.txt")).toBeNull();
  });
});

describe("checkoutArchive", () => {
  let destDir: string;

  beforeEach(async () => {
    destDir = await fs.mkdtemp(join(tmpdir(), "ac-checkout-"));
    showOpenDialog.mockReset();
    showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [destDir],
    });
  });

  afterEach(async () => {
    await fs.rm(destDir, { recursive: true, force: true });
  });

  it("extracts zip entries into the picked directory", async () => {
    const zip = new JSZip();
    zip.file("hello.txt", "hi");
    zip.file("sub/a.md", "# a");
    const archiveBase64 = await zip.generateAsync({ type: "base64" });

    const result = await checkoutArchive(archiveBase64);
    expect(result).toEqual({
      ok: true,
      destName: expect.any(String),
      fileCount: 2,
    });
    expect(await fs.readFile(join(destDir, "hello.txt"), "utf-8")).toBe("hi");
    expect(await fs.readFile(join(destDir, "sub", "a.md"), "utf-8")).toBe(
      "# a",
    );
  });

  it("returns cancelled when dialog is dismissed", async () => {
    showOpenDialog.mockResolvedValue({ canceled: true, filePaths: [] });
    const result = await checkoutArchive("AAAA");
    expect(result).toEqual({ ok: false, reason: "cancelled" });
  });
});

describe("previewArchive", () => {
  const previewRoot = join(tmpdir(), "agentcore-preview");
  const openPath = shell.openPath as unknown as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    openPath.mockClear();
  });

  afterEach(async () => {
    await fs.rm(previewRoot, { recursive: true, force: true });
  });

  it("解压到临时目录并用系统默认程序打开目标文件", async () => {
    const zip = new JSZip();
    zip.file("index.html", "<h1>hi</h1>");
    zip.file("assets/app.css", "body{}");
    const archiveBase64 = await zip.generateAsync({ type: "base64" });

    const result = await previewArchive(archiveBase64, "index.html");
    expect(result).toEqual({ ok: true, fileCount: 2 });
    expect(openPath).toHaveBeenCalledTimes(1);
    const opened = String(openPath.mock.calls[0][0]);
    // 打开的是解压出的 index.html，且落在应用预览临时目录内（未污染工作区/用户目录）。
    expect(opened.endsWith("index.html")).toBe(true);
    expect(opened.startsWith(previewRoot)).toBe(true);
  });

  it("归档中缺目标文件时报错且不打开", async () => {
    const zip = new JSZip();
    zip.file("readme.txt", "x");
    const archiveBase64 = await zip.generateAsync({ type: "base64" });

    const result = await previewArchive(archiveBase64, "index.html");
    expect(result.ok).toBe(false);
    expect(openPath).not.toHaveBeenCalled();
  });

  it("空归档直接报错", async () => {
    const result = await previewArchive("", "index.html");
    expect(result).toEqual({ ok: false, reason: "error", message: "空归档" });
  });
});
