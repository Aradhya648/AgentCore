/**
 * 引用即驻留：把用户选中的本机文件（含区外 / 二进制）复制进对话工作区 ``attachments/``。
 *
 * 绝对路径只在主进程出现；renderer 只拿到 ``name`` / ``workspacePath`` / 可选文本预览。
 * 云占位（OneDrive 按需下载等）在复制前检测，复制本身带短超时，避免 hydration 挂死。
 */

import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { promises as fs, createReadStream, createWriteStream } from "node:fs";
import { basename, extname, join } from "node:path";
import { pipeline } from "node:stream/promises";
import { promisify } from "node:util";
import type { FsResult } from "@shared/ipc-contract";
import { BrowserWindow, app, dialog } from "electron";
import { IMAGE_MIME, TEXT_PREVIEW_CAP } from "./constants";
import { locate, realInside } from "./pathGuard";
import { sniffBinary } from "./preview";
import { ensureReady, getRoot } from "./roots";

const execFileAsync = promisify(execFile);

/** 与服务端 ``workspace_upload_max_bytes`` 对齐。 */
export const ATTACH_MAX_BYTES = 25 * 1024 * 1024;
/** 占位文件 / 网络盘 open 挂起时快速失败（勿吃满 code_execute 的 30–60s）。 */
export const ATTACH_COPY_TIMEOUT_MS = 8_000;

const ATTACHMENTS_DIR = "attachments";
const UNSYNCED_HINT = "文件可能未同步到本地，请在资源管理器中打开一次后再附加";

export interface StageDest {
  rootId: string;
  /** 工作区在授权根下的子路径（scratch / 项目 subpath）；空 = 根自身。 */
  subpath?: string;
}

export interface StagedAttachmentData {
  name: string;
  /** 已写入对话工作区时的相对路径（``attachments/<name>``）。 */
  workspacePath?: string;
  /** 尚未落工作区时的暂存 id（草稿 / 云端待上传）。 */
  stagingId?: string;
  binary: boolean;
  /** UTF-8 文本预览（二进制为空）；供 prompt 内联。 */
  text: string;
  truncated: boolean;
  sizeBytes: number;
}

interface StagingEntry {
  absPath: string;
  name: string;
  binary: boolean;
  text: string;
  truncated: boolean;
  sizeBytes: number;
}

const staging = new Map<string, StagingEntry>();

function stagingDir(): string {
  return join(app.getPath("userData"), "attach-staging");
}

function safeName(name: string): string {
  const base = basename((name || "").replace(/\\/g, "/").trim()).replace(
    /^\.+/,
    "",
  );
  return base || "attachment";
}

function dedupName(name: string, used: Set<string>): string {
  if (!used.has(name)) {
    used.add(name);
    return name;
  }
  const root = name.includes(".") ? name.slice(0, name.lastIndexOf(".")) : name;
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
  let i = 2;
  let candidate = `${root} (${i})${ext}`;
  while (used.has(candidate)) {
    i += 1;
    candidate = `${root} (${i})${ext}`;
  }
  used.add(candidate);
  return candidate;
}

async function listExistingAttachmentNames(
  destRootId: string,
  destSubpath: string,
): Promise<Set<string>> {
  const used = new Set<string>();
  const root = getRoot(destRootId);
  if (!root) return used;
  const rel = destSubpath
    ? `${destSubpath.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "")}/${ATTACHMENTS_DIR}`
    : ATTACHMENTS_DIR;
  const loc = locate(destRootId, rel);
  if ("error" in loc) return used;
  try {
    const entries = await fs.readdir(loc.abs);
    for (const e of entries) used.add(e);
  } catch {
    /* dir missing — empty */
  }
  return used;
}

/**
 * Windows 云占位检测：Offline / RecallOnDataAccess / RecallOnOpen。
 * 非 Windows 返回 false（仍靠复制超时兜底）。
 */
export async function isCloudPlaceholder(absPath: string): Promise<boolean> {
  if (process.platform !== "win32") return false;
  const escaped = absPath.replace(/'/g, "''");
  try {
    const { stdout } = await execFileAsync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `(Get-Item -LiteralPath '${escaped}').Attributes.ToString()`,
      ],
      { timeout: 2_000, windowsHide: true },
    );
    const attrs = stdout.toLowerCase();
    return (
      attrs.includes("offline") ||
      attrs.includes("recallondataaccess") ||
      attrs.includes("recallonopen")
    );
  } catch {
    return false;
  }
}

async function withTimeout<T>(
  p: Promise<T>,
  ms: number,
  label: string,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      p,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label}_TIMEOUT`)), ms);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function copyFileTimed(src: string, dest: string): Promise<void> {
  await fs.mkdir(dirnameSafe(dest), { recursive: true });
  await withTimeout(
    pipeline(createReadStream(src), createWriteStream(dest)),
    ATTACH_COPY_TIMEOUT_MS,
    "COPY",
  );
}

function dirnameSafe(p: string): string {
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return i >= 0 ? p.slice(0, i) : ".";
}

async function resolveDestAbs(
  dest: StageDest,
  fileName: string,
): Promise<FsResult<string>> {
  await ensureReady();
  const root = getRoot(dest.rootId);
  if (!root) {
    return {
      ok: false,
      reason: "本地目录未授权或已移除",
      code: "unauthorized",
    };
  }
  const sub = (dest.subpath || "")
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "");
  const rel = sub
    ? `${sub}/${ATTACHMENTS_DIR}/${fileName}`
    : `${ATTACHMENTS_DIR}/${fileName}`;
  const loc = locate(dest.rootId, rel);
  if ("error" in loc) return loc.error;
  // 目标可能尚不存在——用词法路径 + 父目录 realInside 校验。
  const parentRel = rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "";
  if (parentRel) {
    const parentLoc = locate(dest.rootId, parentRel);
    if ("error" in parentLoc) return parentLoc.error;
    try {
      await fs.mkdir(parentLoc.abs, { recursive: true });
    } catch (e) {
      return {
        ok: false,
        reason: e instanceof Error ? e.message : "无法创建 attachments 目录",
        code: "error",
      };
    }
    const parentReal = await realInside(root, parentLoc.abs);
    if (!parentReal.ok) {
      return {
        ok: false,
        reason: parentReal.reason,
        code: parentReal.code,
      };
    }
  }
  return { ok: true, data: loc.abs };
}

async function materializeSource(
  absPath: string,
): Promise<FsResult<Omit<StagingEntry, "absPath"> & { absPath: string }>> {
  let st: Awaited<ReturnType<typeof fs.stat>>;
  try {
    st = await withTimeout(fs.stat(absPath), 2_000, "STAT");
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.includes("TIMEOUT")) {
      return { ok: false, reason: UNSYNCED_HINT, code: "busy" };
    }
    return { ok: false, reason: "文件不存在或无法访问", code: "not_found" };
  }
  if (!st.isFile()) {
    return { ok: false, reason: "只能附加普通文件", code: "invalid" };
  }
  if (st.size > ATTACH_MAX_BYTES) {
    return {
      ok: false,
      reason: `文件超过 ${Math.round(ATTACH_MAX_BYTES / (1024 * 1024))}MB 上限`,
      code: "invalid",
    };
  }

  const ext = extname(absPath).toLowerCase();
  if (IMAGE_MIME[ext]) {
    return {
      ok: false,
      reason: "暂不支持图片附件（模型尚无视觉能力）",
      code: "invalid",
    };
  }

  if (await isCloudPlaceholder(absPath)) {
    return { ok: false, reason: UNSYNCED_HINT, code: "busy" };
  }

  // 读入内存做二进制嗅探 + 文本预览；整文件仍经流式复制落盘（见 copyFileTimed）。
  let head: Buffer;
  try {
    const fh = await withTimeout(fs.open(absPath, "r"), 2_000, "OPEN");
    try {
      const buf = Buffer.alloc(Math.min(st.size, TEXT_PREVIEW_CAP + 1));
      const { bytesRead } = await withTimeout(
        fh.read(buf, 0, buf.length, 0),
        ATTACH_COPY_TIMEOUT_MS,
        "READ",
      );
      head = buf.subarray(0, bytesRead);
    } finally {
      await fh.close();
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.includes("TIMEOUT")) {
      return { ok: false, reason: UNSYNCED_HINT, code: "busy" };
    }
    return {
      ok: false,
      reason: "读取文件失败",
      code: "error",
    };
  }

  const binary = sniffBinary(head);
  const name = safeName(basename(absPath));
  if (binary) {
    return {
      ok: true,
      data: {
        absPath,
        name,
        binary: true,
        text: "",
        truncated: false,
        sizeBytes: st.size,
      },
    };
  }

  const truncated = st.size > TEXT_PREVIEW_CAP;
  const text = head
    .subarray(0, Math.min(head.length, TEXT_PREVIEW_CAP))
    .toString("utf-8");
  return {
    ok: true,
    data: {
      absPath,
      name,
      binary: false,
      text,
      truncated,
      sizeBytes: st.size,
    },
  };
}

async function writeToDest(
  entry: StagingEntry,
  dest: StageDest,
): Promise<FsResult<StagedAttachmentData>> {
  const used = await listExistingAttachmentNames(
    dest.rootId,
    dest.subpath || "",
  );
  const fileName = dedupName(entry.name, used);
  const destRes = await resolveDestAbs(dest, fileName);
  if (!destRes.ok) return destRes;

  try {
    await copyFileTimed(entry.absPath, destRes.data);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.includes("TIMEOUT")) {
      return { ok: false, reason: UNSYNCED_HINT, code: "busy" };
    }
    return {
      ok: false,
      reason: "复制到工作区失败",
      code: "error",
    };
  }

  return {
    ok: true,
    data: {
      name: fileName,
      workspacePath: `${ATTACHMENTS_DIR}/${fileName}`,
      binary: entry.binary,
      text: entry.text,
      truncated: entry.truncated,
      sizeBytes: entry.sizeBytes,
    },
  };
}

async function stageToTemp(
  entry: StagingEntry,
): Promise<FsResult<StagedAttachmentData>> {
  const id = randomUUID();
  const dir = join(stagingDir(), id);
  await fs.mkdir(dir, { recursive: true });
  const stagedAbs = join(dir, entry.name);
  try {
    await copyFileTimed(entry.absPath, stagedAbs);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    try {
      await fs.rm(dir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
    if (msg.includes("TIMEOUT")) {
      return { ok: false, reason: UNSYNCED_HINT, code: "busy" };
    }
    return { ok: false, reason: "暂存附件失败", code: "error" };
  }

  staging.set(id, {
    ...entry,
    absPath: stagedAbs,
  });

  return {
    ok: true,
    data: {
      name: entry.name,
      stagingId: id,
      binary: entry.binary,
      text: entry.text,
      truncated: entry.truncated,
      sizeBytes: entry.sizeBytes,
    },
  };
}

async function stageFromAbs(
  absPath: string,
  dest?: StageDest,
): Promise<FsResult<StagedAttachmentData>> {
  let resolved = absPath;
  try {
    resolved = await fs.realpath(absPath);
  } catch {
    /* keep lexical */
  }
  const mat = await materializeSource(resolved);
  if (!mat.ok) return mat;
  if (dest) return writeToDest(mat.data, dest);
  return stageToTemp(mat.data);
}

/** 系统文件选择器 → 驻留（有 dest）或暂存。 */
export async function pickAndStageAttachment(
  dest?: StageDest,
): Promise<FsResult<StagedAttachmentData> | null> {
  const win =
    BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
  const result = win
    ? await dialog.showOpenDialog(win, {
        properties: ["openFile"],
        title: "附加文件到对话",
      })
    : await dialog.showOpenDialog({
        properties: ["openFile"],
        title: "附加文件到对话",
      });
  if (result.canceled || result.filePaths.length === 0) return null;
  return stageFromAbs(result.filePaths[0], dest);
}

/** 从已授权根内相对路径驻留（@ 菜单）。 */
export async function stageFromRoot(
  rootId: string,
  relPath: string,
  dest?: StageDest,
): Promise<FsResult<StagedAttachmentData>> {
  await ensureReady();
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) {
    return { ok: false, reason: real.reason, code: real.code };
  }
  return stageFromAbs(real.path, dest);
}

/** 拖拽/粘贴：preload 用 getPathForFile 得到绝对路径后调用（不下发 renderer）。 */
export async function stageFromAbsPath(
  absPath: string,
  dest?: StageDest,
): Promise<FsResult<StagedAttachmentData>> {
  if (!absPath || typeof absPath !== "string") {
    return { ok: false, reason: "无效的请求参数", code: "invalid" };
  }
  return stageFromAbs(absPath, dest);
}

/** 草稿/云端：把暂存文件写入本地工作区 attachments/。 */
export async function finalizeStagedAttachment(
  stagingId: string,
  dest: StageDest,
): Promise<FsResult<StagedAttachmentData>> {
  const entry = staging.get(stagingId);
  if (!entry) {
    return {
      ok: false,
      reason: "附件暂存已失效，请重新附加",
      code: "not_found",
    };
  }
  const out = await writeToDest(entry, dest);
  if (out.ok) {
    staging.delete(stagingId);
    try {
      await fs.rm(join(stagingDir(), stagingId), {
        recursive: true,
        force: true,
      });
    } catch {
      /* ignore */
    }
  }
  return out;
}

/** 云端工作区：取出暂存字节供 PUT /workspace/files（取出后清除暂存）。 */
export async function consumeStagedBytes(
  stagingId: string,
): Promise<FsResult<{ name: string; data: Uint8Array; binary: boolean }>> {
  const entry = staging.get(stagingId);
  if (!entry) {
    return {
      ok: false,
      reason: "附件暂存已失效，请重新附加",
      code: "not_found",
    };
  }
  try {
    const buf = await withTimeout(
      fs.readFile(entry.absPath),
      ATTACH_COPY_TIMEOUT_MS,
      "READ",
    );
    staging.delete(stagingId);
    try {
      await fs.rm(join(stagingDir(), stagingId), {
        recursive: true,
        force: true,
      });
    } catch {
      /* ignore */
    }
    return {
      ok: true,
      data: {
        name: entry.name,
        data: new Uint8Array(buf),
        binary: entry.binary,
      },
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.includes("TIMEOUT")) {
      return { ok: false, reason: UNSYNCED_HINT, code: "busy" };
    }
    return { ok: false, reason: "读取暂存附件失败", code: "error" };
  }
}
