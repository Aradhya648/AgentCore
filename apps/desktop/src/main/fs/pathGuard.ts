import { promises as fs } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
import type { FsErrorCode, FsResult } from "@shared/ipc-contract";
import {
  DEFAULT_WORKSPACE_ROOT_LABEL,
  normalizeWorkspacePath,
} from "../../shared/workspace-path";
import type { StoredRoot } from "./roots";
import { getRoot } from "./roots";

/** 把异常映射为对用户友好的中文原因。 */
export function toReason(e: unknown): string {
  const code = (e as NodeJS.ErrnoException)?.code;
  switch (code) {
    case "ENOENT":
      return "文件或目录不存在";
    case "EACCES":
    case "EPERM":
      return "没有访问权限";
    case "EEXIST":
      return "目标已存在";
    case "ENOTEMPTY":
      return "目录非空";
    case "EBUSY":
      return "文件被占用";
    default:
      return e instanceof Error ? e.message : String(e);
  }
}

/** 构造带判别码的 Fs 失败结果。 */
export function fsErr(code: FsErrorCode, reason: string): FsResult<never> {
  return { ok: false, code, reason };
}

/** 把 Node errno 映射为带码的 FsResult（供 catch 分支使用）。 */
export function fromErrno(e: unknown): FsResult<never> {
  const code = (e as NodeJS.ErrnoException)?.code;
  switch (code) {
    case "ENOENT":
      return fsErr("not_found", "文件或目录不存在");
    case "EACCES":
    case "EPERM":
      return fsErr("denied", "没有访问权限");
    case "EEXIST":
      return fsErr("exists", "目标已存在");
    case "EBUSY":
      return fsErr("busy", "文件被占用");
    default:
      return fsErr("error", toReason(e));
  }
}

/** realpath 复核结果：成功路径，或不存在 / 越界 / 其他错误。 */
export type RealInsideResult =
  | { ok: true; path: string }
  | {
      ok: false;
      code: Extract<FsErrorCode, "not_found" | "out_of_root" | "error">;
      reason: string;
    };

/** 把 realInside 失败折叠为 FsResult（保留判别码与中文 message）。 */
export function realFail(
  r: Extract<RealInsideResult, { ok: false }>,
): FsResult<never> {
  return fsErr(r.code, r.reason);
}

/**
 * 词法校验：解析相对路径并确认仍在根内（不触盘）。返回绝对路径或 null。
 * 先走 ``normalizeWorkspacePath``（与后端 ``resolve_safe_path`` 同契约）。
 */
export function resolveLexical(
  root: StoredRoot,
  relPath: string,
): string | null {
  const label = root.name?.trim() || DEFAULT_WORKSPACE_ROOT_LABEL;
  const normalized = normalizeWorkspacePath(relPath, label);
  const abs = resolve(root.absPath, normalized);
  const rel = relative(root.absPath, abs);
  if (rel === "") return abs; // 根目录自身
  if (rel.startsWith("..") || isAbsolute(rel)) return null;
  return abs;
}

/**
 * realpath 复核：解析真实路径并确认仍在根内（防符号链接逃逸）。
 * ENOENT → `not_found`；逃逸 → `out_of_root`——二者不再折叠。
 */
export async function realInside(
  root: StoredRoot,
  abs: string,
): Promise<RealInsideResult> {
  try {
    const real = await fs.realpath(abs);
    const rel = relative(root.absPath, real);
    if (rel === "") return { ok: true, path: real };
    if (rel.startsWith("..") || isAbsolute(rel)) {
      return { ok: false, code: "out_of_root", reason: "路径越界，已拒绝" };
    }
    return { ok: true, path: real };
  } catch (e) {
    if ((e as NodeJS.ErrnoException)?.code === "ENOENT") {
      return { ok: false, code: "not_found", reason: "文件或目录不存在" };
    }
    return { ok: false, code: "error", reason: toReason(e) };
  }
}

/** 取根并做词法解析；失败返回判别式错误。 */
export function locate(
  rootId: string,
  relPath: string,
): { root: StoredRoot; abs: string } | { error: FsResult<never> } {
  const root = getRoot(rootId);
  if (!root) return { error: fsErr("unauthorized", "目录未授权或已移除") };
  const abs = resolveLexical(root, relPath);
  if (!abs) return { error: fsErr("out_of_root", "路径越界，已拒绝") };
  return { root, abs };
}

/**
 * 词法 + realpath 双守卫解析 cwd（process / pty 共用）。
 * 空 / ``.`` / 裸 ``/`` → 根自身；相对路径相对根；绝对路径须仍落在根内。
 * symlink 祖先逃逸 → `out_of_root`。
 */
export async function resolveCwdInside(
  root: StoredRoot,
  cwdArg?: string | null,
): Promise<{ ok: true; cwd: string } | { ok: false; detail: string }> {
  const label = root.name?.trim() || DEFAULT_WORKSPACE_ROOT_LABEL;
  const normalized =
    cwdArg == null || cwdArg === ""
      ? "."
      : normalizeWorkspacePath(cwdArg, label);
  let abs: string | null;
  if (normalized === "." || normalized === "") {
    abs = root.absPath;
  } else if (isAbsolute(normalized)) {
    abs = resolve(normalized);
    const rel = relative(root.absPath, abs);
    if (rel !== "" && (rel.startsWith("..") || isAbsolute(rel))) {
      return { ok: false, detail: "cwd 越出工作区根" };
    }
  } else {
    abs = resolveLexical(root, normalized);
    if (!abs) return { ok: false, detail: "cwd 越出工作区根" };
  }

  const real = await realInside(root, abs);
  if (!real.ok) {
    if (real.code === "out_of_root") {
      return { ok: false, detail: "cwd 越出工作区根" };
    }
    if (real.code === "not_found") {
      return { ok: false, detail: "工作区路径不存在" };
    }
    return { ok: false, detail: real.reason };
  }
  return { ok: true, cwd: real.path };
}
