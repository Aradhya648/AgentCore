import { promises as fs } from "node:fs";
import type { FsResult } from "@shared/ipc-contract";
import { clipboard, shell } from "electron";
import { fsErr, locate, realFail, realInside } from "./pathGuard";
import { ensureReady } from "./roots";

// --- 系统集成（在资源管理器中显示 / 用默认程序打开 / 复制路径 / 回收站）---
//
// 把 renderer 的 `{rootId, relPath}` 解析为绝对路径并 realpath 校验在根内（防越界 /
// 符号链接逃逸），再交给系统：定位 / 打开 / 写剪贴板 / 软删。**绝对路径只在主进程出现**，
// 从不下发 renderer，沿用本服务的安全不变量。仅本地源会调到这里（云端无本机路径）。

/** 在系统文件管理器中定位该路径（`shell.showItemInFolder`）。
 * 路径尚不存在时懒建目录（裸聊 scratch 首次「打开此对话文件夹」）。 */
export async function reveal(
  rootId: string,
  relPath: string,
): Promise<FsResult> {
  await ensureReady();
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  let real = await realInside(loc.root, loc.abs);
  if (!real.ok) {
    if (real.code === "not_found" && relPath) {
      try {
        await fs.mkdir(loc.abs, { recursive: true });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        return { ok: false, reason: msg || "无法创建目录", code: "error" };
      }
      real = await realInside(loc.root, loc.abs);
    }
    if (!real.ok) return realFail(real);
  }
  shell.showItemInFolder(real.path);
  return { ok: true, data: undefined };
}

/** 用系统默认程序打开该路径（`shell.openPath` 返回非空串即失败原因）。 */
export async function openWithDefaultApp(
  rootId: string,
  relPath: string,
): Promise<FsResult> {
  await ensureReady();
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) return realFail(real);
  const err = await shell.openPath(real.path);
  if (err) return { ok: false, reason: err, code: "error" };
  return { ok: true, data: undefined };
}

/** 把该路径移入系统回收站（`shell.trashItem`，软删；不硬删）。 */
export async function trashPath(
  rootId: string,
  relPath: string,
): Promise<FsResult> {
  await ensureReady();
  if (!relPath) return fsErr("invalid", "不能回收根目录");
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) {
    // 尚未物化的懒建 scratch → 视为已无物可回收。
    if (real.code === "not_found") return { ok: true, data: undefined };
    return realFail(real);
  }
  try {
    await shell.trashItem(real.path);
    return { ok: true, data: undefined };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, reason: msg || "移入回收站失败", code: "error" };
  }
}

/** 把该路径的绝对路径写入系统剪贴板（写入在主进程完成，绝对路径不进 renderer）。 */
export async function copyPath(
  rootId: string,
  relPath: string,
): Promise<FsResult> {
  await ensureReady();
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) return realFail(real);
  clipboard.writeText(real.path);
  return { ok: true, data: undefined };
}
