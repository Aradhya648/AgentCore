import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import { basename, dirname, isAbsolute, join, relative } from "node:path";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { shell } from "electron";
import { WORKSPACE_READ_MAX } from "../constants";
import { realInside, resolveLexical, toReason } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { opErr, opOk } from "./result";
import { applyTextReplace } from "./textReplace";

/** 原子写：同目录临时文件 + rename，避免进程中断在用户真实磁盘上留下半截文件。 */
export async function atomicWrite(abs: string, data: Buffer): Promise<void> {
  const tmp = join(dirname(abs), `.tmp_ws_${randomUUID()}`);
  try {
    await fs.writeFile(tmp, data);
    await fs.rename(tmp, abs);
  } catch (e) {
    await fs.rm(tmp, { force: true }).catch(() => {});
    throw e;
  }
}

/**
 * 解析「目标可不存在」的写入路径并校验在根内（write/write_bytes/mkdir/move 目标用）。
 *
 * 词法定位先拒 `..`/绝对/同名兄弟；再对「最深的已存在祖先」做 realpath 复核，防止经
 * 符号链接祖先逃逸——与服务端 `resolve_safe_path` 的 `.resolve()` 语义对齐（不存在的
 * 尾段无法是符号链接，故只需校验已存在部分）。返回可安全写入的绝对路径，越界返回 null。
 */
export async function resolveWritable(
  root: StoredRoot,
  relPath: string,
): Promise<string | null> {
  const abs = resolveLexical(root, relPath);
  if (!abs) return null;
  let existing = abs;
  const tail: string[] = [];
  for (;;) {
    try {
      await fs.lstat(existing);
      break;
    } catch {
      const parent = dirname(existing);
      if (parent === existing) break; // 抵达文件系统根（根目录必存在，不应触发）
      tail.unshift(basename(existing));
      existing = parent;
    }
  }
  const realExisting = await realInside(root, existing);
  if (!realExisting.ok) return null;
  return tail.length > 0 ? join(realExisting.path, ...tail) : realExisting.path;
}

export async function opReadBytes(
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
  if (st.size > WORKSPACE_READ_MAX) {
    return opErr("WorkspaceIOError", "文件过大，无法读取");
  }
  const real = await realInside(root, abs);
  if (!real.ok) {
    return real.code === "out_of_root"
      ? opErr("OutsideWorkspace", relPath)
      : opErr("PathNotFound", relPath);
  }
  try {
    // JSON 无字节类型：以 base64 回填，服务端 LocalWorkspace.read_bytes 解码还原。
    return opOk((await fs.readFile(real.path)).toString("base64"));
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
}

export async function opWrite(
  root: StoredRoot,
  relPath: string,
  content: string,
): Promise<WorkspaceOpResult> {
  const target = await resolveWritable(root, relPath);
  if (!target) return opErr("OutsideWorkspace", relPath);
  if (target === root.absPath) return opErr("WorkspaceIOError", "目标是目录");
  try {
    await fs.mkdir(dirname(target), { recursive: true });
    await atomicWrite(target, Buffer.from(content, "utf-8"));
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk([...content].length); // 码点数，与服务端 len(content) 对齐
}

export async function opAppend(
  root: StoredRoot,
  relPath: string,
  content: string,
): Promise<WorkspaceOpResult> {
  const target = await resolveWritable(root, relPath);
  if (!target) return opErr("OutsideWorkspace", relPath);
  if (target === root.absPath) return opErr("WorkspaceIOError", "目标是目录");
  try {
    await fs.mkdir(dirname(target), { recursive: true });
    let exists = false;
    try {
      const st = await fs.stat(target);
      if (!st.isFile()) return opErr("NotAFile", relPath);
      exists = true;
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") {
        return opErr("WorkspaceIOError", toReason(e));
      }
    }
    if (exists) {
      await fs.appendFile(target, content, "utf-8");
    } else {
      await atomicWrite(target, Buffer.from(content, "utf-8"));
    }
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk([...content].length);
}

export async function opWriteBytes(
  root: StoredRoot,
  relPath: string,
  base64Data: string,
): Promise<WorkspaceOpResult> {
  const target = await resolveWritable(root, relPath);
  if (!target) return opErr("OutsideWorkspace", relPath);
  if (target === root.absPath) return opErr("WorkspaceIOError", "目标是目录");
  const data = Buffer.from(base64Data, "base64");
  try {
    await fs.mkdir(dirname(target), { recursive: true });
    await atomicWrite(target, data);
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk(data.length);
}

export async function opMkdir(
  root: StoredRoot,
  relPath: string,
): Promise<WorkspaceOpResult> {
  const target = await resolveWritable(root, relPath);
  if (!target) return opErr("OutsideWorkspace", relPath);
  if (target === root.absPath) return opErr("OutsideWorkspace", relPath); // 根已存在
  try {
    await fs.lstat(target);
    return opErr("AlreadyExists", relPath);
  } catch {
    // 不存在 —— 符合预期
  }
  try {
    await fs.mkdir(target, { recursive: true });
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk(null);
}

function isAgentcoreRel(relPath: string): boolean {
  const p = relPath.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  return p === ".agentcore" || p.startsWith(".agentcore/");
}

/** 无系统回收站时：移入工作区 `.agentcore/trash/<id>/` 并写 meta（对齐服务端 soft_delete）。 */
async function softDeleteToWorkspaceTrash(
  root: StoredRoot,
  realPath: string,
  relPath: string,
): Promise<WorkspaceOpResult> {
  const entryId = randomUUID().replace(/-/g, "");
  const entryDir = join(root.absPath, ".agentcore", "trash", entryId);
  const dest = join(entryDir, "content");
  try {
    const st = await fs.lstat(realPath);
    await fs.mkdir(entryDir, { recursive: true });
    await fs.rename(realPath, dest);
    const meta = {
      original_path: relPath.replace(/\\/g, "/"),
      deleted_at: new Date().toISOString(),
      is_dir: st.isDirectory(),
      name: basename(realPath),
    };
    await fs.writeFile(
      join(entryDir, "meta.json"),
      `${JSON.stringify(meta, null, 2)}\n`,
      "utf-8",
    );
    return opOk(null);
  } catch (e) {
    await fs.rm(entryDir, { recursive: true, force: true }).catch(() => {});
    return opErr("WorkspaceIOError", toReason(e));
  }
}

export async function opDelete(
  root: StoredRoot,
  relPath: string,
  permanent = false,
): Promise<WorkspaceOpResult> {
  const abs = resolveLexical(root, relPath);
  if (!abs) return opErr("OutsideWorkspace", relPath);
  if (abs === root.absPath) return opErr("OutsideWorkspace", relPath); // 不删根
  try {
    await fs.lstat(abs);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return opErr("PathNotFound", relPath);
    }
    return opErr("WorkspaceIOError", toReason(e));
  }
  const real = await realInside(root, abs);
  if (!real.ok) {
    return real.code === "out_of_root"
      ? opErr("OutsideWorkspace", relPath)
      : opErr("PathNotFound", relPath);
  }
  const hard = permanent || isAgentcoreRel(relPath);
  try {
    if (hard) {
      await fs.rm(real.path, { recursive: true, force: false });
      return opOk(null);
    }
    // 默认可逆：系统回收站；失败则落工作区软删区（无回收站 / 权限拒绝等）。
    try {
      await shell.trashItem(real.path);
      return opOk(null);
    } catch {
      return softDeleteToWorkspaceTrash(root, real.path, relPath);
    }
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
}

export async function opCopy(
  root: StoredRoot,
  src: string,
  dst: string,
): Promise<WorkspaceOpResult> {
  const srcAbs = resolveLexical(root, src);
  if (!srcAbs) return opErr("OutsideWorkspace", src);
  if (srcAbs === root.absPath) return opErr("OutsideWorkspace", src);
  try {
    await fs.lstat(srcAbs);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return opErr("PathNotFound", src);
    }
    return opErr("WorkspaceIOError", toReason(e));
  }
  const srcReal = await realInside(root, srcAbs);
  if (!srcReal.ok) {
    return srcReal.code === "out_of_root"
      ? opErr("OutsideWorkspace", src)
      : opErr("PathNotFound", src);
  }

  const dstTarget = await resolveWritable(root, dst);
  if (!dstTarget) return opErr("OutsideWorkspace", dst);
  if (dstTarget === root.absPath) return opErr("OutsideWorkspace", dst);

  // 禁止把目录复制进自身或其子树（否则 fs.cp 会自我递归）。
  const intoRel = relative(srcReal.path, dstTarget);
  if (intoRel === "" || (!intoRel.startsWith("..") && !isAbsolute(intoRel))) {
    return opErr("WorkspaceIOError", "不能复制到自身或其子目录");
  }

  let dstExists = true;
  try {
    await fs.lstat(dstTarget);
  } catch {
    dstExists = false;
  }
  if (dstExists) return opErr("AlreadyExists", dst);
  try {
    await fs.mkdir(dirname(dstTarget), { recursive: true });
    await fs.cp(srcReal.path, dstTarget, {
      recursive: true,
      errorOnExist: true,
    });
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk(null);
}

export async function opMove(
  root: StoredRoot,
  src: string,
  dst: string,
): Promise<WorkspaceOpResult> {
  const srcAbs = resolveLexical(root, src);
  if (!srcAbs) return opErr("OutsideWorkspace", src);
  if (srcAbs === root.absPath) return opErr("OutsideWorkspace", src);
  try {
    await fs.lstat(srcAbs);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return opErr("PathNotFound", src);
    }
    return opErr("WorkspaceIOError", toReason(e));
  }
  const srcReal = await realInside(root, srcAbs);
  if (!srcReal.ok) {
    return srcReal.code === "out_of_root"
      ? opErr("OutsideWorkspace", src)
      : opErr("PathNotFound", src);
  }

  const dstTarget = await resolveWritable(root, dst);
  if (!dstTarget) return opErr("OutsideWorkspace", dst);
  if (dstTarget === root.absPath) return opErr("OutsideWorkspace", dst);
  let dstExists = true;
  try {
    await fs.lstat(dstTarget);
  } catch {
    dstExists = false;
  }
  if (dstExists) return opErr("AlreadyExists", dst);
  try {
    await fs.mkdir(dirname(dstTarget), { recursive: true });
    await fs.rename(srcReal.path, dstTarget);
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk(null);
}

export async function opReplace(
  root: StoredRoot,
  relPath: string,
  oldStr: string,
  newStr: string,
  all: boolean,
): Promise<WorkspaceOpResult> {
  const abs = resolveLexical(root, relPath);
  if (!abs) return opErr("OutsideWorkspace", relPath);
  try {
    await fs.lstat(abs);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return opErr("PathNotFound", relPath);
    }
    return opErr("WorkspaceIOError", toReason(e));
  }
  const real = await realInside(root, abs);
  if (!real.ok) {
    return real.code === "out_of_root"
      ? opErr("OutsideWorkspace", relPath)
      : opErr("PathNotFound", relPath);
  }
  let st: import("node:fs").Stats;
  try {
    st = await fs.stat(real.path);
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  if (!st.isFile()) return opErr("NotAFile", relPath);

  let content: string;
  try {
    const buf = await fs.readFile(real.path);
    // fatal 解码：非法 UTF-8 抛 TypeError → NotUTF8（对齐服务端 read_bytes().decode）。
    content = new TextDecoder("utf-8", { fatal: true }).decode(buf);
  } catch (e) {
    if (e instanceof TypeError) return opErr("NotUTF8", relPath);
    return opErr("WorkspaceIOError", toReason(e));
  }

  // Exact first, then LF-normalized fallback (mirrors server text_replace.py).
  const replaced = applyTextReplace(content, oldStr, newStr, all);
  if (!replaced.ok) {
    if (replaced.kind === "AmbiguousMatch") {
      return opErr(
        "AmbiguousMatch",
        `${replaced.count} matches`,
        replaced.count,
      );
    }
    return opErr("NoMatch", relPath);
  }
  try {
    await atomicWrite(real.path, Buffer.from(replaced.content, "utf-8"));
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  return opOk({ count: replaced.count, first_line: replaced.firstLine });
}
