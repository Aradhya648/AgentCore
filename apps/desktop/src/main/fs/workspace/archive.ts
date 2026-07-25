import { promises as fs } from "node:fs";
import { join } from "node:path";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import ignore, { type Ignore } from "ignore";
import JSZip from "jszip";
import {
  ARCHIVE_MAX_BYTES,
  ARCHIVE_MAX_FILES,
  LIST_FILES_SKIP_DIRS,
} from "../constants";
import { toReason } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { opErr, opOk } from "./result";

// --- 本地→云交接打包 op（双模式工作区 P2e / e1）---
//
// 把整个绑定根打包成单个 zip（base64 回填），供服务端解包暂存并快照。套用忽略规则：
// 默认跳过集（与 @ 提及列举一致的依赖/构建/VCS 噪音）+ 根 .gitignore，避免把 node_modules
// 之类塞进交接。设文件数/字节上限防超大仓 OOM 或撑爆通道，超限置 truncated（部分交接好过
// 整体失败）。只在根内 walk 且不跟随符号链接，故越界天然不可能。

/** 载入忽略规则：默认跳过集 + 根 `.gitignore`（缺失则仅默认集）。 */
async function loadIgnore(rootAbs: string): Promise<Ignore> {
  const ig = ignore();
  // 默认跳过集按目录规则加入（"name/" 匹配整棵子树）+ *.db。
  ig.add([...LIST_FILES_SKIP_DIRS].map((d) => `${d}/`));
  ig.add(["*.db"]);
  try {
    ig.add(await fs.readFile(join(rootAbs, ".gitignore"), "utf-8"));
  } catch {
    // 无 .gitignore —— 仅用默认集
  }
  return ig;
}

export async function opArchive(
  root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const useIgnore = args.ignore !== false; // 默认 true
  // Optional workspace subpath (项目子目录 / 裸聊 conversations/<id>)：只打包该子树，
  // zip 条目用工作区相对路径（剥掉 directory 前缀），与 LocalWorkspace 前缀口径一致。
  const rawDir = typeof args.directory === "string" ? args.directory : "";
  const directory = rawDir.replace(/^\/+|\/+$/g, "");
  if (
    directory === ".." ||
    directory.startsWith("../") ||
    directory.includes("/../") ||
    directory.endsWith("/..")
  ) {
    return opErr("OutsideWorkspace", directory);
  }
  const walkRootAbs = directory ? join(root.absPath, directory) : root.absPath;
  // Ignore rules stay rooted at the authorized FS root (.gitignore at bind root).
  const ig = useIgnore ? await loadIgnore(root.absPath) : null;
  const zip = new JSZip();
  let fileCount = 0;
  let totalBytes = 0;
  let truncated = false;
  let stop = false;

  /** ``relFromWalk`` = path under the walk root (= workspace-relative when scoped). */
  const walk = async (absDir: string, relFromWalk: string): Promise<void> => {
    if (stop) return;
    let dirents: import("node:fs").Dirent[];
    try {
      dirents = await fs.readdir(absDir, { withFileTypes: true });
    } catch {
      return; // 单个子目录不可读不影响整体
    }
    for (const d of dirents) {
      if (stop) break;
      if (d.isSymbolicLink()) continue; // 不跟随链接，防逃逸/环路
      const childRelWalk = relFromWalk ? `${relFromWalk}/${d.name}` : d.name;
      // Ignore matcher sees container-relative paths (under the bind root).
      const childRelRoot = directory
        ? `${directory}/${childRelWalk}`
        : childRelWalk;
      if (d.isDirectory()) {
        if (ig?.ignores(`${childRelRoot}/`)) continue; // 命中目录规则 → 跳整棵子树
        await walk(join(absDir, d.name), childRelWalk);
      } else if (d.isFile()) {
        if (ig?.ignores(childRelRoot)) continue;
        if (fileCount >= ARCHIVE_MAX_FILES) {
          truncated = true;
          stop = true;
          break;
        }
        let buf: Buffer;
        try {
          buf = await fs.readFile(join(absDir, d.name));
        } catch {
          continue; // 单文件读失败跳过
        }
        if (totalBytes + buf.length > ARCHIVE_MAX_BYTES) {
          truncated = true;
          stop = true;
          break;
        }
        zip.file(childRelWalk, buf);
        fileCount++;
        totalBytes += buf.length;
      }
    }
  };

  try {
    await walk(walkRootAbs, "");
    const archive = await zip.generateAsync({
      type: "base64",
      compression: "DEFLATE",
    });
    return opOk({
      archive,
      file_count: fileCount,
      total_bytes: totalBytes,
      truncated,
    });
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
}
