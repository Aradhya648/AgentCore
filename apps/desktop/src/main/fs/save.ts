/**
 * 单文件「另存为」（fs:saveFile）：renderer 把已取到的字节交主进程，这里弹系统保存
 * 对话框并原子落盘。
 *
 * 为什么存在：Electron 不支持 `<a download>` + blob:（不触发 will-download，且 blob:
 * 导航被主窗口 will-navigate 安全守卫拦截），renderer 侧「浏览器式下载」在桌面端
 * 静默失败。刻意**不**放宽 will-navigate 放行 blob:（会打开导航逃逸面），而是把
 * 落盘挪进主进程——与 checkoutArchive（目录导出）同一模式。
 */

import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import { basename, dirname, join } from "node:path";
import type { SaveFileResult } from "@shared/ipc-contract";
import { BrowserWindow, app, dialog } from "electron";

/**
 * 把（可能来自服务端 Content-Disposition / 用户数据的）建议文件名净化成安全的
 * 单段 basename：剥路径分隔、Windows 保留字符与控制字符，去首尾点/空格（Windows
 * 不接受结尾点/空格），限长，空则回退 "download"。仅用于对话框 defaultPath 预填；
 * 最终写入路径完全由用户在对话框里选定。
 */
export function sanitizeFilename(name: string): string {
  const cleaned = name
    .replace(/[/\\]+/g, "_")
    // biome-ignore lint/suspicious/noControlCharactersInRegex: 剥离文件名中的控制字符正是本意
    .replace(/[<>:"|?*\u0000-\u001f]/g, "_")
    .replace(/^[\s.]+|[\s.]+$/g, "")
    .slice(0, 150);
  return cleaned || "download";
}

/**
 * 弹「另存为」对话框（预填净化后的 `suggestedName`、默认下载目录），把 `bytes`
 * 原子写入所选路径（同目录临时文件 + rename，写失败不留半截文件）。
 * 取消 → `{ reason: "cancelled" }`（非错误）；绝对路径不回传（只回 basename）。
 */
export async function saveBytesToDisk(
  suggestedName: string,
  bytes: Uint8Array,
  parent?: BrowserWindow | null,
): Promise<SaveFileResult> {
  const fileName = sanitizeFilename(suggestedName);
  let defaultPath: string;
  try {
    defaultPath = join(app.getPath("downloads"), fileName);
  } catch {
    // 极端环境（无下载目录）——让对话框自选起始位置。
    defaultPath = fileName;
  }

  const win =
    parent ??
    BrowserWindow.getFocusedWindow() ??
    BrowserWindow.getAllWindows()[0];
  const options: Electron.SaveDialogOptions = {
    defaultPath,
    properties: ["createDirectory", "showOverwriteConfirmation"],
  };
  const result = win
    ? await dialog.showSaveDialog(win, options)
    : await dialog.showSaveDialog(options);
  if (result.canceled || !result.filePath) {
    return { ok: false, reason: "cancelled" };
  }

  const target = result.filePath;
  const tmp = join(dirname(target), `.tmp_save_${randomUUID()}`);
  try {
    await fs.writeFile(tmp, bytes);
    await fs.rename(tmp, target);
  } catch (e) {
    await fs.rm(tmp, { force: true }).catch(() => {});
    return {
      ok: false,
      reason: "error",
      message: e instanceof Error ? e.message : "写入文件失败",
    };
  }
  // 回用户实际选定的文件名（对话框里可能改名），仅 basename、不回绝对路径。
  return { ok: true, fileName: basename(target) || fileName };
}
