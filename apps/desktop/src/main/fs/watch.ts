import { type FSWatcher, watch as fsWatch } from "node:fs";
import { FS_CHANNELS } from "@shared/ipc-contract";
import type { WebContents } from "electron";
import { resolveLexical } from "./pathGuard";
import { getRoot } from "./roots";

// watch 状态：key = `${rootId}::${relPath}`
const watchers = new Map<string, FSWatcher>();
const debounceTimers = new Map<string, NodeJS.Timeout>();

export function watchDir(
  wc: WebContents,
  rootId: string,
  relPath: string,
): void {
  const root = getRoot(rootId);
  if (!root) return;
  const abs = resolveLexical(root, relPath);
  if (!abs) return;
  const key = `${rootId}::${relPath}`;
  if (watchers.has(key)) return;
  try {
    const w = fsWatch(abs, { persistent: false }, () => {
      const prev = debounceTimers.get(key);
      if (prev) clearTimeout(prev);
      debounceTimers.set(
        key,
        setTimeout(() => {
          debounceTimers.delete(key);
          if (!wc.isDestroyed()) {
            wc.send(FS_CHANNELS.changed, { rootId, relPath });
          }
        }, 150),
      );
    });
    w.on("error", () => closeWatcher(key));
    watchers.set(key, w);
  } catch {
    // 目录不可 watch（如已删除）—— 忽略，由后续 listDir 暴露错误
  }
}

function closeWatcher(key: string): void {
  const w = watchers.get(key);
  if (w) {
    w.close();
    watchers.delete(key);
  }
  const t = debounceTimers.get(key);
  if (t) {
    clearTimeout(t);
    debounceTimers.delete(key);
  }
}

export function unwatchDir(rootId: string, relPath: string): void {
  closeWatcher(`${rootId}::${relPath}`);
}

export function closeWatchersForRoot(rootId: string): void {
  const prefix = `${rootId}::`;
  for (const key of [...watchers.keys()]) {
    if (key.startsWith(prefix)) closeWatcher(key);
  }
}
