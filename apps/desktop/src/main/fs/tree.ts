import { promises as fs } from "node:fs";
import { basename, dirname, isAbsolute, join, relative } from "node:path";
import type {
  FsCreateKind,
  FsEntry,
  FsFileRef,
  FsResult,
} from "@shared/ipc-contract";
import { LIST_FILES_CAP, LIST_FILES_MAX_DEPTH } from "./constants";
import { fromErrno, fsErr, locate, realFail, realInside } from "./pathGuard";
import { ensureReady } from "./roots";
import { resolveWritable } from "./workspace/write";
import {
  shouldSkipSystemWorkspaceEntry,
  shouldSkipWorkspaceEntry,
} from "./workspaceIgnore";

/**
 * 工作区扁平文件索引（共享走法）：广度优先逐层展开 `real` 根，受深度（`LIST_FILES_MAX_DEPTH`）
 * 与总数（`LIST_FILES_CAP`）双重限制；跳过依赖/构建/VCS 目录，不跟随符号链接（避免环路与越界）。
 * `truncated` 表示命中 cap 截断。@ 提及检索（`listFiles`）与 worker 工作区清单（`opIndexFiles`）
 * 共用同一套走法，使本地根与云端 `ServerWorkspace.index_files` 呈现一致的扁平视图。
 *
 * `order`：`"path"`（默认）= 字母序、**不 stat**（@ 提及/选择器走法，延迟敏感）；`"recent"` =
 * 按 mtime 倒序（每文件多一次 `stat`），供 worker 清单在大树里把预算花在最可能相关的新文件上。
 */
export async function collectWorkspaceFiles(
  real: string,
  order: "path" | "recent" = "path",
): Promise<{ files: FsFileRef[]; truncated: boolean }> {
  const recent = order === "recent";
  const collected: Array<{ ref: FsFileRef; mtimeMs: number }> = [];
  let truncated = false;
  const stack: Array<{ abs: string; rel: string; depth: number }> = [
    { abs: real, rel: "", depth: 0 },
  ];
  while (stack.length > 0) {
    if (collected.length >= LIST_FILES_CAP) {
      truncated = true;
      break;
    }
    const cur = stack.pop();
    if (!cur) break;
    let dirents: import("node:fs").Dirent[];
    try {
      dirents = await fs.readdir(cur.abs, { withFileTypes: true });
    } catch {
      continue; // 单个子目录不可读不影响整体
    }
    for (const d of dirents) {
      if (d.isSymbolicLink()) continue;
      const childRel = cur.rel ? `${cur.rel}/${d.name}` : d.name;
      if (d.isDirectory()) {
        if (shouldSkipWorkspaceEntry(d.name, true, cur.rel)) continue;
        if (cur.depth + 1 <= LIST_FILES_MAX_DEPTH) {
          stack.push({
            abs: join(cur.abs, d.name),
            rel: childRel,
            depth: cur.depth + 1,
          });
        }
      } else if (d.isFile()) {
        if (shouldSkipWorkspaceEntry(d.name, false, cur.rel)) continue;
        let mtimeMs = 0;
        if (recent) {
          try {
            mtimeMs = (await fs.stat(join(cur.abs, d.name))).mtimeMs;
          } catch {
            mtimeMs = 0; // unreadable stat → sinks to the bottom of the recent sort
          }
        }
        collected.push({ ref: { relPath: childRel, name: d.name }, mtimeMs });
        if (collected.length >= LIST_FILES_CAP) {
          truncated = true;
          break;
        }
      }
    }
  }
  if (recent) {
    collected.sort((a, b) => b.mtimeMs - a.mtimeMs); // newest first
  } else {
    collected.sort((a, b) => a.ref.relPath.localeCompare(b.ref.relPath, "zh"));
  }
  return { files: collected.map((c) => c.ref), truncated };
}

export async function listDir(
  rootId: string,
  relPath: string,
): Promise<FsResult<FsEntry[]>> {
  await ensureReady();
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) return realFail(real);
  try {
    const dirents = await fs.readdir(real.path, { withFileTypes: true });
    const entries: FsEntry[] = [];
    for (const d of dirents) {
      const isDir = d.isDirectory();
      // 文件 UI：仅系统噪音；媒体/压缩包等 AI 噪音仍可见（交付物）。
      if (shouldSkipSystemWorkspaceEntry(d.name, isDir, relPath)) continue;
      const childRel = relPath ? `${relPath}/${d.name}` : d.name;
      let size: number | null = null;
      let modifiedMs: number | null = null;
      try {
        const st = await fs.stat(join(real.path, d.name));
        size = isDir ? null : st.size;
        modifiedMs = st.mtimeMs;
      } catch {
        // 单个项 stat 失败（如失效符号链接）不影响整体列举
      }
      entries.push({
        name: d.name,
        relPath: childRel,
        kind: isDir ? "dir" : "file",
        size,
        modifiedMs,
      });
    }
    entries.sort((a, b) =>
      a.kind === b.kind
        ? a.name.localeCompare(b.name, "zh")
        : a.kind === "dir"
          ? -1
          : 1,
    );
    return { ok: true, data: entries };
  } catch (e) {
    return fromErrno(e);
  }
}

export async function listFiles(
  rootId: string,
): Promise<FsResult<FsFileRef[]>> {
  await ensureReady();
  const loc = locate(rootId, "");
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) return realFail(real);
  try {
    const { files } = await collectWorkspaceFiles(real.path);
    return { ok: true, data: files };
  } catch (e) {
    return fromErrno(e);
  }
}

export function isValidName(name: string): boolean {
  return (
    name.length > 0 &&
    name !== "." &&
    name !== ".." &&
    !name.includes("/") &&
    !name.includes("\\")
  );
}

export async function rename(
  rootId: string,
  relPath: string,
  newName: string,
): Promise<FsResult> {
  await ensureReady();
  if (!isValidName(newName)) return fsErr("invalid", "名称非法");
  if (!relPath) return fsErr("invalid", "不能重命名根目录");
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const srcReal = await realInside(loc.root, loc.abs);
  if (!srcReal.ok) return realFail(srcReal);
  const destAbs = join(dirname(loc.abs), newName);
  const destRel = relative(loc.root.absPath, destAbs);
  if (destRel.startsWith("..") || isAbsolute(destRel)) {
    return fsErr("out_of_root", "目标越界，已拒绝");
  }
  try {
    await fs.access(destAbs);
    return fsErr("exists", "同名文件已存在");
  } catch {
    // 目标不存在 —— 符合预期
  }
  try {
    await fs.rename(srcReal.path, destAbs);
    return { ok: true, data: undefined };
  } catch (e) {
    return fromErrno(e);
  }
}

export async function move(
  rootId: string,
  srcRelPath: string,
  destDirRelPath: string,
): Promise<FsResult> {
  await ensureReady();
  if (!srcRelPath) return fsErr("invalid", "不能移动根目录");
  const srcLoc = locate(rootId, srcRelPath);
  if ("error" in srcLoc) return srcLoc.error;
  const destLoc = locate(rootId, destDirRelPath);
  if ("error" in destLoc) return destLoc.error;

  const srcReal = await realInside(srcLoc.root, srcLoc.abs);
  if (!srcReal.ok) return realFail(srcReal);

  // 目标目录可不存在：resolveWritable + mkdir recursive（懒物化工作区首写粘贴）。
  const destDirTarget = await resolveWritable(destLoc.root, destDirRelPath);
  if (!destDirTarget) return fsErr("out_of_root", "目标越界，已拒绝");
  try {
    await fs.mkdir(destDirTarget, { recursive: true });
  } catch (e) {
    return fromErrno(e);
  }
  const destDirCheck = await realInside(destLoc.root, destDirTarget);
  if (!destDirCheck.ok) return realFail(destDirCheck);
  try {
    const st = await fs.stat(destDirCheck.path);
    if (!st.isDirectory()) return fsErr("invalid", "目标不是目录");
  } catch (e) {
    return fromErrno(e);
  }

  // 禁止把目录移动进自身或其子树
  const intoRel = relative(srcReal.path, destDirCheck.path);
  if (intoRel === "" || (!intoRel.startsWith("..") && !isAbsolute(intoRel))) {
    return fsErr("invalid", "不能移动到自身或其子目录");
  }

  const destAbs = join(destDirCheck.path, basename(srcReal.path));
  try {
    await fs.access(destAbs);
    return fsErr("exists", "目标位置已存在同名项");
  } catch {
    // 目标不存在 —— 符合预期
  }
  try {
    await fs.rename(srcReal.path, destAbs);
    return { ok: true, data: undefined };
  } catch (e) {
    return fromErrno(e);
  }
}

/**
 * 复制文件/目录到**完整目标路径** `destRelPath`（与 move 收「目标目录」不同，copy 收含
 * 最终名的完整路径，故能在同目录内另存为新名——去重粘贴所需）。`fs.cp(recursive)` 递归
 * 复制；拒绝复制根、覆盖已存在目标、以及把目录复制进自身或其子树（否则会自我递归）。
 */
export async function copy(
  rootId: string,
  srcRelPath: string,
  destRelPath: string,
): Promise<FsResult> {
  await ensureReady();
  if (!srcRelPath) return fsErr("invalid", "不能复制根目录");
  const srcLoc = locate(rootId, srcRelPath);
  if ("error" in srcLoc) return srcLoc.error;
  const srcReal = await realInside(srcLoc.root, srcLoc.abs);
  if (!srcReal.ok) return realFail(srcReal);

  // 目标可不存在：经 resolveWritable 校验在根内（含对已存在祖先的 realpath 复核）。
  const dstTarget = await resolveWritable(srcLoc.root, destRelPath);
  if (!dstTarget) return fsErr("out_of_root", "目标越界，已拒绝");
  if (dstTarget === srcLoc.root.absPath) {
    return fsErr("invalid", "不能覆盖根目录");
  }

  // 禁止把目录复制进自身或其子树（否则 fs.cp 会自我递归）。文件复制为同名兄弟不受影响。
  const intoRel = relative(srcReal.path, dstTarget);
  if (intoRel === "" || (!intoRel.startsWith("..") && !isAbsolute(intoRel))) {
    return fsErr("invalid", "不能复制到自身或其子目录");
  }

  try {
    await fs.access(dstTarget);
    return fsErr("exists", "目标位置已存在同名项");
  } catch {
    // 目标不存在 —— 符合预期
  }
  try {
    await fs.mkdir(dirname(dstTarget), { recursive: true });
    await fs.cp(srcReal.path, dstTarget, {
      recursive: true,
      errorOnExist: true,
    });
    return { ok: true, data: undefined };
  } catch (e) {
    return fromErrno(e);
  }
}

export async function create(
  rootId: string,
  relPath: string,
  kind: FsCreateKind,
): Promise<FsResult> {
  await ensureReady();
  const name = basename(relPath);
  if (!isValidName(name)) return fsErr("invalid", "名称非法");
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;

  // 目标可不存在：resolveWritable + 父目录 mkdir recursive（懒物化工作区首写）。
  const target = await resolveWritable(loc.root, relPath);
  if (!target) return fsErr("out_of_root", "路径越界，已拒绝");
  if (target === loc.root.absPath) {
    return fsErr("invalid", "不能覆盖根目录");
  }

  try {
    await fs.access(target);
    return fsErr("exists", "已存在同名项");
  } catch {
    // 不存在 —— 符合预期
  }
  try {
    await fs.mkdir(dirname(target), { recursive: true });
    if (kind === "dir") {
      await fs.mkdir(target);
    } else {
      const fh = await fs.open(target, "wx");
      await fh.close();
    }
    return { ok: true, data: undefined };
  } catch (e) {
    return fromErrno(e);
  }
}

export async function remove(
  rootId: string,
  relPath: string,
): Promise<FsResult> {
  await ensureReady();
  if (!relPath) return fsErr("invalid", "不能删除根目录");
  const loc = locate(rootId, relPath);
  if ("error" in loc) return loc.error;
  const real = await realInside(loc.root, loc.abs);
  if (!real.ok) return realFail(real);
  try {
    await fs.rm(real.path, { recursive: true, force: false });
    return { ok: true, data: undefined };
  } catch (e) {
    return fromErrno(e);
  }
}
