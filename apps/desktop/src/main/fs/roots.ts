import { promises as fs } from "node:fs";
import { join } from "node:path";
import { app } from "electron";

export interface StoredRoot {
  id: string;
  name: string;
  absPath: string;
  /** W3: session-only grant — not persisted to fs-roots.json. */
  sessionOnly?: boolean;
  conversationId?: string;
  /**
   * Session access mode. Prefer over legacy ``readonly``.
   * ``readonly`` = W3 read-only; ``organize`` = move/copy/mkdir/trash-delete.
   */
  mode?: "readonly" | "organize";
  /** @deprecated Prefer ``mode``. Kept for older in-memory session roots. */
  readonly?: boolean;
  /** Model-facing alias under ``external/<alias>/``. */
  alias?: string;
}

let roots = new Map<string, StoredRoot>();
let rootsReady: Promise<void> | null = null;

function storeFilePath(): string {
  return join(app.getPath("userData"), "fs-roots.json");
}

async function loadRoots(): Promise<void> {
  try {
    const raw = await fs.readFile(storeFilePath(), "utf-8");
    const arr = JSON.parse(raw) as StoredRoot[];
    // Drop any accidentally persisted session roots.
    roots = new Map(
      arr
        .filter((r) => !r.sessionOnly)
        .map((r) => [r.id, { id: r.id, name: r.name, absPath: r.absPath }]),
    );
  } catch {
    roots = new Map();
  }
}

async function saveRoots(): Promise<void> {
  const arr = [...roots.values()].filter((r) => !r.sessionOnly);
  try {
    await fs.writeFile(storeFilePath(), JSON.stringify(arr, null, 2));
  } catch (e) {
    console.error("[fs-service] 持久化授权根失败:", e);
  }
}

export async function ensureReady(): Promise<void> {
  if (rootsReady) await rootsReady;
}

export function initRoots(): void {
  rootsReady = loadRoots();
}

export function getRoot(id: string): StoredRoot | undefined {
  return roots.get(id);
}

export function setRoot(root: StoredRoot): void {
  roots.set(root.id, root);
}

export function deleteRoot(id: string): boolean {
  return roots.delete(id);
}

/** Permanent (non-session) roots for settings / project binding. */
export function getAllRoots(): StoredRoot[] {
  return [...roots.values()].filter((r) => !r.sessionOnly);
}

export function findRootByAbsPath(absPath: string): StoredRoot | undefined {
  return [...roots.values()].find((r) => r.absPath === absPath);
}

export function listSessionRoots(conversationId: string): StoredRoot[] {
  return [...roots.values()].filter(
    (r) => r.sessionOnly && r.conversationId === conversationId,
  );
}

export function clearSessionRoots(conversationId: string): string[] {
  const removed: string[] = [];
  for (const [id, r] of roots) {
    if (r.sessionOnly && r.conversationId === conversationId) {
      roots.delete(id);
      removed.push(id);
    }
  }
  return removed;
}

export function revokeSessionRoot(
  conversationId: string,
  rootId: string,
): boolean {
  const r = roots.get(rootId);
  if (!r?.sessionOnly || r.conversationId !== conversationId) return false;
  roots.delete(rootId);
  return true;
}

/**
 * 按 id 取一个已授权根（含绝对路径），供 sidecar 模式把 `rootId` 解析成 `workspaceRoot`。
 *
 * 与 renderer 的 `{rootId, relPath}` 寻址同源（绝对路径只存在于主进程）；本地引擎
 * （sidecar）跑在用户机器上，需要这个绝对路径作为绑定根。未授权 / 已移除返回 null。
 */
export async function getStoredRoot(
  rootId: string,
): Promise<StoredRoot | null> {
  await ensureReady();
  return roots.get(rootId) ?? null;
}

export { saveRoots };
