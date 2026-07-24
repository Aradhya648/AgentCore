/**
 * Trust-on-first-use for local project directories (P2 optional).
 *
 * User-level persistence via the unified uiStorage layer (`agentcore:` 命名空间，
 * preview 自动切内存后端). When a local folder path has never been trusted and
 * is not a git working tree, callers may suggest ``observe`` or prompt once:
 * 「信任此目录？」.
 */

import { uiGet, uiRemove, uiSet } from "@/lib/uiStorage";

const STORAGE_KEY = "trustedWorkspaceRoots.v1";

function readRoots(): string[] {
  const parsed = uiGet<unknown>(STORAGE_KEY);
  if (!Array.isArray(parsed)) return [];
  return parsed.filter((x): x is string => typeof x === "string");
}

function writeRoots(roots: string[]): void {
  uiSet(STORAGE_KEY, [...new Set(roots)]);
}

function normalizeRoot(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

export function isWorkspaceRootTrusted(path: string): boolean {
  const key = normalizeRoot(path);
  return readRoots().some((r) => normalizeRoot(r) === key);
}

export function trustWorkspaceRoot(path: string): void {
  const roots = readRoots();
  roots.push(path);
  writeRoots(roots);
}

/**
 * Suggest observe for first-touch local dirs that are not trusted.
 * Git repos are treated as already-known projects (no prompt).
 */
export function suggestObserveForUntrustedLocal(opts: {
  localRootPath: string | null | undefined;
  isGitRepo: boolean;
}): boolean {
  if (!opts.localRootPath) return false;
  if (opts.isGitRepo) return false;
  return !isWorkspaceRootTrusted(opts.localRootPath);
}

/** One-shot confirm; returns true if the user trusts the directory. */
export function confirmTrustLocalDirectory(path: string): boolean {
  if (isWorkspaceRootTrusted(path)) return true;
  const ok = window.confirm(
    "此本地目录尚未标记为可信。\n\n信任后，新会话可使用「开工授权」权限模式；否则建议保持「只观察」。\n\n信任此目录？",
  );
  if (ok) trustWorkspaceRoot(path);
  return ok;
}

/** Test helper. */
export function clearTrustedWorkspaceRootsForTests(): void {
  uiRemove(STORAGE_KEY);
}
