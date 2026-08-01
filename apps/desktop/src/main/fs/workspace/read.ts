import { promises as fs } from "node:fs";
import { join, relative } from "node:path";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import {
  LIST_FILES_MAX_DEPTH,
  WORKSPACE_LIST_MAX,
  WORKSPACE_READ_MAX,
} from "../constants";
import { realInside, resolveLexical, toReason } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { collectWorkspaceFiles } from "../tree";
import { shouldSkipWorkspaceEntry } from "../workspaceIgnore";
import { globToRegExp, opErr, opOk, toPosix } from "./result";

function isAccessDeniedError(e: unknown): boolean {
  const code = (e as NodeJS.ErrnoException)?.code;
  return code === "EACCES" || code === "EPERM" || code === "EBUSY";
}

export async function opRead(
  root: StoredRoot,
  relPath: string,
): Promise<WorkspaceOpResult> {
  const abs = resolveLexical(root, relPath);
  if (!abs) return opErr("OutsideWorkspace", relPath);
  let st: import("node:fs").Stats;
  try {
    st = await fs.stat(abs);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return opErr("PathNotFound", relPath);
    }
    return opErr("WorkspaceIOError", toReason(e));
  }
  if (!st.isFile()) return opErr("NotAFile", relPath);
  if (st.size > WORKSPACE_READ_MAX)
    return opErr("WorkspaceIOError", "文件过大，无法读取");
  const real = await realInside(root, abs);
  if (!real.ok) {
    return real.code === "out_of_root"
      ? opErr("OutsideWorkspace", relPath)
      : opErr("PathNotFound", relPath);
  }
  try {
    const buf = await fs.readFile(real.path);
    if (buf.includes(0))
      return opErr("WorkspaceIOError", "二进制文件，无法以文本读取");
    return opOk(buf.toString("utf-8"));
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
}

export async function opList(
  root: StoredRoot,
  directory: string,
  pattern: string,
): Promise<WorkspaceOpResult> {
  const baseAbs = resolveLexical(root, directory);
  if (!baseAbs) return opErr("OutsideWorkspace", directory);
  const baseReal = await realInside(root, baseAbs);
  // 服务端 list：base 非目录（含不存在）一律 NotADirectory。
  let baseStat: import("node:fs").Stats | undefined;
  if (baseReal.ok) {
    try {
      baseStat = await fs.stat(baseReal.path);
    } catch {
      baseStat = undefined;
    }
  }
  if (!baseReal.ok || !baseStat?.isDirectory()) {
    if (baseReal.ok === false && baseReal.code === "out_of_root") {
      return opErr("OutsideWorkspace", directory);
    }
    return opErr("NotADirectory", directory);
  }

  const recursive = pattern.includes("**");
  const re = globToRegExp(pattern);
  const results: { path: string; is_dir: boolean }[] = [];
  const listBaseRel = (() => {
    const d = directory.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    return d === "." ? "" : d;
  })();

  const walk = async (
    absDir: string,
    relFromBase: string,
    depth: number,
  ): Promise<void> => {
    if (results.length >= WORKSPACE_LIST_MAX) return;
    let dirents: import("node:fs").Dirent[];
    try {
      dirents = await fs.readdir(absDir, { withFileTypes: true });
    } catch {
      // Per-subdir unreadability: skip; do not fail the whole list.
      return;
    }
    dirents.sort((a, b) => a.name.localeCompare(b.name));
    for (const d of dirents) {
      if (results.length >= WORKSPACE_LIST_MAX) break;
      const isDir = d.isDirectory();
      const parentRel = relFromBase
        ? listBaseRel
          ? `${listBaseRel}/${relFromBase}`
          : relFromBase
        : listBaseRel;
      // Name-first dir ignore (locked ``.pytest_tmp`` etc.) before trusting type.
      if (shouldSkipWorkspaceEntry(d.name, true, parentRel)) continue;
      if (!isDir && shouldSkipWorkspaceEntry(d.name, false, parentRel))
        continue;
      const childRel = relFromBase ? `${relFromBase}/${d.name}` : d.name;
      if (re.test(childRel)) {
        results.push({
          path: toPosix(relative(root.absPath, join(absDir, d.name))),
          is_dir: isDir,
        });
      }
      if (recursive && isDir && depth + 1 <= LIST_FILES_MAX_DEPTH) {
        await walk(join(absDir, d.name), childRel, depth + 1);
      }
    }
  };

  await walk(baseReal.path, "", 0);
  results.sort((a, b) => a.path.localeCompare(b.path));
  return opOk(results.slice(0, WORKSPACE_LIST_MAX));
}

function splitLinesLikePython(text: string): string[] {
  if (text === "") return [];
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  if (normalized.endsWith("\n") && lines.length > 0) {
    lines.pop();
  }
  return lines;
}

export async function opReadLines(
  root: StoredRoot,
  relPath: string,
  offset: number,
  limit: number | null,
): Promise<WorkspaceOpResult> {
  const abs = resolveLexical(root, relPath);
  if (!abs) return opErr("OutsideWorkspace", relPath);
  let st: import("node:fs").Stats;
  try {
    st = await fs.stat(abs);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return opErr("PathNotFound", relPath);
    }
    return opErr("WorkspaceIOError", toReason(e));
  }
  if (!st.isFile()) return opErr("NotAFile", relPath);
  if (st.size > WORKSPACE_READ_MAX)
    return opErr("WorkspaceIOError", "文件过大，无法读取");
  const real = await realInside(root, abs);
  if (!real.ok) {
    return real.code === "out_of_root"
      ? opErr("OutsideWorkspace", relPath)
      : opErr("PathNotFound", relPath);
  }
  try {
    const buf = await fs.readFile(real.path);
    if (buf.includes(0))
      return opErr("WorkspaceIOError", "二进制文件，无法以文本读取");
    const lines = splitLinesLikePython(buf.toString("utf-8"));
    const total = lines.length;
    const startIdx = Math.max(0, offset - 1);
    if (startIdx >= total) {
      return opOk({
        lines: [],
        start_line: offset,
        end_line: offset - 1,
        total_lines: total,
      });
    }
    const endIdx =
      limit == null ? total : Math.min(total, startIdx + Math.max(0, limit));
    const selected = lines.slice(startIdx, endIdx);
    return opOk({
      lines: selected,
      start_line: startIdx + 1,
      end_line: endIdx,
      total_lines: total,
    });
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
}

export async function opListTree(
  root: StoredRoot,
  directory: string,
  pattern: string,
  maxDepth: number,
  maxEntries: number,
): Promise<WorkspaceOpResult> {
  const baseAbs = resolveLexical(root, directory);
  if (!baseAbs) return opErr("OutsideWorkspace", directory);
  const baseReal = await realInside(root, baseAbs);
  let baseStat: import("node:fs").Stats | undefined;
  if (baseReal.ok) {
    try {
      baseStat = await fs.stat(baseReal.path);
    } catch {
      baseStat = undefined;
    }
  }
  if (!baseReal.ok || !baseStat?.isDirectory()) {
    if (baseReal.ok === false && baseReal.code === "out_of_root") {
      return opErr("OutsideWorkspace", directory);
    }
    return opErr("NotADirectory", directory);
  }

  const entries: { path: string; is_dir: boolean; depth: number }[] = [];
  let truncated = false;
  let elidedCount = 0;
  const warnings: string[] = [];
  const nameFilter = pattern || "*";
  const matchName = (name: string, isDir: boolean) =>
    isDir || globToRegExp(nameFilter).test(name);

  const walk = async (
    absDir: string,
    parentRel: string,
    depth: number,
    isRoot: boolean,
  ): Promise<void> => {
    if (depth > maxDepth) return;
    let dirents: import("node:fs").Dirent[];
    try {
      dirents = await fs.readdir(absDir, { withFileTypes: true });
    } catch (e) {
      if (!isRoot && isAccessDeniedError(e)) {
        warnings.push(`跳过无权限目录：${parentRel || "."}`);
        return;
      }
      throw e;
    }
    dirents.sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
    );
    for (const d of dirents) {
      // Name-first ignore prune before descending into locked noise dirs.
      if (shouldSkipWorkspaceEntry(d.name, true, parentRel)) continue;
      const isDir = d.isDirectory() && !d.isSymbolicLink();
      if (!isDir && shouldSkipWorkspaceEntry(d.name, false, parentRel))
        continue;
      const childAbs = join(absDir, d.name);
      const childRel = parentRel ? `${parentRel}/${d.name}` : d.name;
      if (!matchName(d.name, isDir)) continue;
      if (entries.length >= maxEntries) {
        truncated = true;
        elidedCount += 1;
        continue;
      }
      entries.push({
        path: toPosix(relative(root.absPath, childAbs)),
        is_dir: isDir,
        depth,
      });
      if (isDir && depth < maxDepth) {
        await walk(childAbs, childRel, depth + 1, false);
      }
    }
  };

  try {
    const baseRel = toPosix(relative(root.absPath, baseReal.path));
    await walk(baseReal.path, baseRel === "." ? "" : baseRel, 1, true);
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk({
    entries,
    truncated,
    elided_count: elidedCount,
    warnings,
  });
}

// index_files：把绑定根（或其 `base` 子树）扁平索引成相对文件路径列表（忽略目录剪枝 + cap），
// 返回 {paths, truncated}。服务端 LocalWorkspace.index_files 经此打通，使 @ 提及与 worker
// 工作区清单在本地根上与云端 ServerWorkspace.index_files 行为一致。`order` 选排序
// （"recent" 按 mtime 倒序供清单预算，否则字母序）。
//
// `base` = 工作区子路径（工作区对称化 D1a）：把索引限定到该子树，并把子路径前缀**拼回**各结果
// （故返回的是 root-相对路径），服务端 `LocalWorkspace._out` 再剥成工作区相对——与 list/grep
// 回填 root-相对、服务端统一剥前缀的约定一致。`""` / `"."` = 整根（现行为，无前缀）。子树尚不
// 存在（裸聊懒建后尚未产文件）→ 空列表。
export async function opIndexFiles(
  root: StoredRoot,
  order: "path" | "recent",
  base = "",
): Promise<WorkspaceOpResult> {
  const sub = base === "." ? "" : base.replace(/^\/+|\/+$/g, "");
  const baseAbs = resolveLexical(root, sub || ".");
  if (!baseAbs) return opErr("OutsideWorkspace", base);
  const baseReal = await realInside(root, baseAbs);
  // 子树尚不存在（裸聊懒建后尚未产文件）→ 空列表；越界仍硬错。
  if (!baseReal.ok) {
    if (baseReal.code === "out_of_root") {
      return opErr("OutsideWorkspace", base);
    }
    return opOk({ paths: [], truncated: false });
  }
  const { files, truncated } = await collectWorkspaceFiles(
    baseReal.path,
    order,
  );
  const prefix = sub ? `${sub}/` : "";
  return opOk({ paths: files.map((f) => prefix + f.relPath), truncated });
}
