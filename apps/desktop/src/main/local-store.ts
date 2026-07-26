/**
 * Desktop local-store (N4-A 只读离线) — main-process persistence under
 * `<userData>/local-store/`. Caps: 20 opened conversations · ~50 MiB.
 *
 * Cloud remains the authority on reconnect; this is a read cache only.
 */
import {
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import { join } from "node:path";
import {
  LOCAL_STORE_CHANNELS,
  LOCAL_STORE_MAX_BYTES,
  LOCAL_STORE_MAX_CONVERSATIONS,
  type LocalStoreApi,
  type LocalStoreConversationMeta,
  type LocalStoreConversationPayload,
  type LocalStorePutShellMeta,
  type LocalStoreShellMeta,
  type LocalStoreSnapshot,
  type LocalStoreUser,
} from "@shared/local-store-contract";
import { app, ipcMain } from "electron";

const META_VERSION = 1 as const;

type MetaFile = LocalStoreSnapshot;

/**
 * Serialize every meta.json read-modify-write.
 *
 * The renderer fires cacheShellMeta / cacheOpenedConversation from independent,
 * unawaited effects (auth, workspaces, conversations), so the IPC handlers
 * interleave. Without this queue two defects show up: the shared `meta.json.tmp`
 * is written twice and renamed twice (ENOENT / EPERM on Windows), and — silently,
 * the worse one — a `readMeta` → mutate → write pair that straddles another
 * writer drops that writer's patch entirely.
 *
 * Not reentrant: take it at the public-function boundary only, never inside
 * writeMetaAtomic. Read-only paths (getSnapshot / hasCache / getConversation)
 * stay lock-free — atomic rename means they always see a complete file.
 */
let metaChain: Promise<unknown> = Promise.resolve();

function withMetaLock<T>(fn: () => Promise<T>): Promise<T> {
  // then(fn, fn): a rejected predecessor must not stall the queue.
  const run = metaChain.then(fn, fn);
  metaChain = run.catch(() => undefined);
  return run;
}

let tmpSeq = 0;

/** Unique temp path — a shared one lets a second instance steal our rename. */
function tmpPathFor(target: string): string {
  tmpSeq += 1;
  return `${target}.${process.pid}-${tmpSeq}.tmp`;
}

async function writeFileAtomic(target: string, data: string): Promise<void> {
  const tmp = tmpPathFor(target);
  try {
    await writeFile(tmp, data, "utf-8");
    await rename(tmp, target);
  } catch (err) {
    await unlink(tmp).catch(() => undefined);
    throw err;
  }
}

function rootDir(): string {
  return join(app.getPath("userData"), "local-store");
}

function metaPath(): string {
  return join(rootDir(), "meta.json");
}

function convDir(): string {
  return join(rootDir(), "conversations");
}

function convPath(id: string): string {
  return join(convDir(), `${id}.json`);
}

async function ensureDirs(): Promise<void> {
  await mkdir(convDir(), { recursive: true });
}

async function readMeta(): Promise<MetaFile> {
  try {
    const raw = await readFile(metaPath(), "utf-8");
    const parsed = JSON.parse(raw) as MetaFile;
    if (parsed?.version !== META_VERSION) return emptyMeta();
    return {
      version: META_VERSION,
      user: parsed.user ?? null,
      conversations: Array.isArray(parsed.conversations)
        ? parsed.conversations
        : [],
      folders: Array.isArray(parsed.folders) ? parsed.folders : [],
      workspaces: Array.isArray(parsed.workspaces) ? parsed.workspaces : [],
      totalBytes: typeof parsed.totalBytes === "number" ? parsed.totalBytes : 0,
    };
  } catch {
    return emptyMeta();
  }
}

function emptyMeta(): MetaFile {
  return {
    version: META_VERSION,
    user: null,
    conversations: [],
    folders: [],
    workspaces: [],
    totalBytes: 0,
  };
}

async function writeMetaAtomic(meta: MetaFile): Promise<void> {
  await ensureDirs();
  await writeFileAtomic(metaPath(), JSON.stringify(meta, null, 2));
}

function shellOf(meta: MetaFile): LocalStoreShellMeta {
  return {
    user: meta.user,
    conversations: meta.conversations,
    folders: meta.folders,
    workspaces: meta.workspaces,
    totalBytes: meta.totalBytes,
  };
}

function byteSizeOf(payload: LocalStoreConversationPayload): number {
  return Buffer.byteLength(JSON.stringify(payload), "utf-8");
}

/**
 * Evict oldest-opened conversations until under the count + byte caps.
 * Pure helper — exported for unit tests.
 */
export function evictLocalStoreIndex(
  conversations: LocalStoreConversationMeta[],
  maxCount = LOCAL_STORE_MAX_CONVERSATIONS,
  maxBytes = LOCAL_STORE_MAX_BYTES,
): { kept: LocalStoreConversationMeta[]; evictedIds: string[] } {
  const sorted = [...conversations].sort((a, b) => b.openedAt - a.openedAt);
  const kept: LocalStoreConversationMeta[] = [];
  const evictedIds: string[] = [];
  let bytes = 0;
  for (const row of sorted) {
    const next = bytes + (row.byteSize || 0);
    if (kept.length >= maxCount || next > maxBytes) {
      evictedIds.push(row.id);
      continue;
    }
    kept.push(row);
    bytes = next;
  }
  return { kept, evictedIds };
}

async function deleteConvFile(id: string): Promise<void> {
  try {
    await unlink(convPath(id));
  } catch {
    /* missing ok */
  }
}

async function applyEviction(meta: MetaFile): Promise<MetaFile> {
  const { kept, evictedIds } = evictLocalStoreIndex(meta.conversations);
  for (const id of evictedIds) await deleteConvFile(id);
  const totalBytes = kept.reduce((n, c) => n + (c.byteSize || 0), 0);
  return { ...meta, conversations: kept, totalBytes };
}

async function putOpenedConversation(
  payload: LocalStoreConversationPayload,
): Promise<LocalStoreShellMeta> {
  return withMetaLock(async () => {
    await ensureDirs();
    const size = byteSizeOf(payload);
    const openedAt = Date.now();
    const row: LocalStoreConversationMeta = {
      ...payload.conversation,
      openedAt,
      byteSize: size,
    };
    const toWrite: LocalStoreConversationPayload = {
      ...payload,
      conversation: row,
    };
    await writeFileAtomic(convPath(row.id), JSON.stringify(toWrite));

    let meta = await readMeta();
    meta = {
      ...meta,
      conversations: [
        row,
        ...meta.conversations.filter((c) => c.id !== row.id),
      ],
    };
    meta = await applyEviction(meta);
    await writeMetaAtomic(meta);
    return shellOf(meta);
  });
}

async function putShellMeta(
  patch: LocalStorePutShellMeta,
): Promise<LocalStoreShellMeta> {
  return withMetaLock(async () => {
    let meta = await readMeta();
    if (patch.user !== undefined) meta = { ...meta, user: patch.user };
    if (patch.folders) meta = { ...meta, folders: patch.folders };
    if (patch.workspaces) meta = { ...meta, workspaces: patch.workspaces };
    if (patch.conversations) {
      // Only refresh meta for conversations already in the opened cache — never
      // inflate the index with the full online list (N4-A: opened-only, max 20).
      const byId = new Map(patch.conversations.map((c) => [c.id, c]));
      meta = {
        ...meta,
        conversations: meta.conversations.map((old) => {
          const fresh = byId.get(old.id);
          if (!fresh) return old;
          return {
            ...fresh,
            openedAt: old.openedAt,
            byteSize: old.byteSize,
          };
        }),
      };
    }
    await writeMetaAtomic(meta);
    return shellOf(meta);
  });
}

async function getConversation(
  id: string,
): Promise<LocalStoreConversationPayload | null> {
  try {
    const raw = await readFile(convPath(id), "utf-8");
    return JSON.parse(raw) as LocalStoreConversationPayload;
  } catch {
    return null;
  }
}

async function hasCache(): Promise<boolean> {
  const meta = await readMeta();
  return meta.user != null || meta.conversations.length > 0;
}

async function getSnapshot(): Promise<LocalStoreSnapshot | null> {
  const meta = await readMeta();
  if (meta.user == null && meta.conversations.length === 0) return null;
  return meta;
}

async function clearAll(): Promise<void> {
  // Under the lock: an in-flight write must not recreate meta.json after the rm.
  await withMetaLock(async () => {
    try {
      await rm(rootDir(), { recursive: true, force: true });
    } catch {
      /* ok */
    }
  });
}

/** Register IPC handlers (call once from app.whenReady). */
export function registerLocalStoreIpc(): void {
  ipcMain.handle(LOCAL_STORE_CHANNELS.hasCache, () => hasCache());
  ipcMain.handle(LOCAL_STORE_CHANNELS.getSnapshot, () => getSnapshot());
  ipcMain.handle(LOCAL_STORE_CHANNELS.getConversation, (_e, id: string) =>
    getConversation(id),
  );
  ipcMain.handle(
    LOCAL_STORE_CHANNELS.putOpenedConversation,
    (_e, payload: LocalStoreConversationPayload) =>
      putOpenedConversation(payload),
  );
  ipcMain.handle(
    LOCAL_STORE_CHANNELS.putShellMeta,
    (_e, patch: LocalStorePutShellMeta) => putShellMeta(patch),
  );
  ipcMain.handle(LOCAL_STORE_CHANNELS.clear, () => clearAll());
}

/** Test seam: re-export shape for LocalStoreApi completeness. */
export type { LocalStoreApi, LocalStoreUser };

/** Sweep orphan conversation files not listed in meta (best-effort). */
export async function sweepOrphanLocalStoreFiles(): Promise<void> {
  // Under the lock: a conversation being written right now is not yet in meta,
  // and deleting it mid-write would orphan the index row instead of the file.
  await withMetaLock(async () => {
    try {
      await ensureDirs();
      const meta = await readMeta();
      const keep = new Set(meta.conversations.map((c) => c.id));
      const files = await readdir(convDir());
      for (const f of files) {
        if (!f.endsWith(".json")) continue;
        const id = f.slice(0, -".json".length);
        if (!keep.has(id)) await deleteConvFile(id);
      }
    } catch {
      /* ignore */
    }
  });
}
