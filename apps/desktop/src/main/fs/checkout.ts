/**
 * 云 scratch → 本地单向 checkout（双模式工作区 §八.7）。
 *
 * 用户选目录后，把云端快照 zip 解压落地。不登记授权根、不绑工作区——纯导出。
 */

import { promises as fs } from "node:fs";
import { basename, dirname, join, normalize, sep } from "node:path";
import { BrowserWindow, app, dialog, shell } from "electron";
import JSZip from "jszip";

export type CheckoutArchiveResult =
  | { ok: true; destName: string; fileCount: number }
  | { ok: false; reason: "cancelled" }
  | { ok: false; reason: "error"; message: string };

export type PreviewArchiveResult =
  | { ok: true; fileCount: number }
  | { ok: false; reason: "error"; message: string };

/** 拒绝 zip 内含 `..` / 绝对路径的条目，防止写出目标目录外。 */
export function safeJoinUnder(
  destAbs: string,
  entryPath: string,
): string | null {
  const normalized = entryPath.replace(/\\/g, "/").replace(/^\/+/, "");
  if (!normalized || normalized.includes("\0")) return null;
  const parts = normalized.split("/").filter((p) => p && p !== ".");
  if (parts.some((p) => p === "..")) return null;
  const target = normalize(join(destAbs, ...parts));
  const rootWithSep = destAbs.endsWith(sep) ? destAbs : destAbs + sep;
  if (target !== destAbs && !target.startsWith(rootWithSep)) return null;
  return target;
}

/** 解压 base64 zip 到 `destAbs`（防 zip-slip，跳过越界/绝对路径条目），返回落盘文件数。 */
async function extractZipTo(
  archiveBase64: string,
  destAbs: string,
): Promise<number> {
  const zip = await JSZip.loadAsync(archiveBase64, { base64: true });
  let fileCount = 0;
  for (const entry of Object.values(zip.files)) {
    if (entry.dir) continue;
    const target = safeJoinUnder(destAbs, entry.name);
    if (!target) continue;
    await fs.mkdir(dirname(target), { recursive: true });
    await fs.writeFile(target, await entry.async("nodebuffer"));
    fileCount++;
  }
  return fileCount;
}

/**
 * 弹目录选择器，把 base64 zip 解压到所选目录（覆盖同名文件）。
 * 成功后在系统文件管理器中打开该目录。
 */
export async function checkoutArchive(
  archiveBase64: string,
): Promise<CheckoutArchiveResult> {
  if (!archiveBase64) {
    return { ok: false, reason: "error", message: "空归档" };
  }

  const win =
    BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
  const result = win
    ? await dialog.showOpenDialog(win, {
        properties: ["openDirectory", "createDirectory"],
      })
    : await dialog.showOpenDialog({
        properties: ["openDirectory", "createDirectory"],
      });
  if (result.canceled || result.filePaths.length === 0) {
    return { ok: false, reason: "cancelled" };
  }

  let destAbs: string;
  try {
    destAbs = await fs.realpath(result.filePaths[0]);
  } catch {
    destAbs = result.filePaths[0];
  }

  try {
    const fileCount = await extractZipTo(archiveBase64, destAbs);
    try {
      await shell.openPath(destAbs);
    } catch {
      /* best-effort reveal */
    }
    return {
      ok: true,
      destName: basename(destAbs) || destAbs,
      fileCount,
    };
  } catch (e) {
    return {
      ok: false,
      reason: "error",
      message: e instanceof Error ? e.message : "解压失败",
    };
  }
}

/**
 * 「在浏览器打开」：把 base64 zip 解压到应用临时目录（每次独立子目录），再用系统默认
 * 程序打开 `openRelPath`——HTML 交给系统浏览器，得到完整 JS + 多文件相对资源的真实
 * 效果。不弹目录、不登记根、不绑工作区（纯只读预览，落临时目录交由 OS 回收）。
 */
export async function previewArchive(
  archiveBase64: string,
  openRelPath: string,
): Promise<PreviewArchiveResult> {
  if (!archiveBase64) {
    return { ok: false, reason: "error", message: "空归档" };
  }
  const rel = openRelPath.replace(/\\/g, "/").replace(/^\/+/, "");
  if (!rel) {
    return { ok: false, reason: "error", message: "未指定要打开的文件" };
  }
  try {
    const baseDir = join(app.getPath("temp"), "agentcore-preview");
    await fs.mkdir(baseDir, { recursive: true });
    const destAbs = await fs.mkdtemp(join(baseDir, "p-"));
    const fileCount = await extractZipTo(archiveBase64, destAbs);
    const target = safeJoinUnder(destAbs, rel);
    if (!target) {
      return { ok: false, reason: "error", message: "非法的文件路径" };
    }
    try {
      await fs.access(target);
    } catch {
      return { ok: false, reason: "error", message: "归档中找不到该文件" };
    }
    // shell.openPath 返回空串表示成功，非空即系统层错误信息。
    const err = await shell.openPath(target);
    if (err) return { ok: false, reason: "error", message: err };
    return { ok: true, fileCount };
  } catch (e) {
    return {
      ok: false,
      reason: "error",
      message: e instanceof Error ? e.message : "预览失败",
    };
  }
}
