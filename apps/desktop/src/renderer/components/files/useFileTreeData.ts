import { type FileNode, type FileSource, parentDir } from "@/lib/fileSource";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

export type DirStatus = "loading" | "ready" | "error";

/** Dirs first, then by name — the canonical tree ordering (mutates + returns). */
export function sortNodes(nodes: FileNode[]): FileNode[] {
  return nodes.sort((a, b) =>
    a.isDir !== b.isDir ? (a.isDir ? -1 : 1) : a.name.localeCompare(b.name),
  );
}

/**
 * Fold a flat recursive listing into a per-parent children map (dir → its direct
 * children). The root bucket ("") is always present; every listed directory gets
 * an entry too (empty if it has no listed children) so the tree can render it as
 * a known-empty folder rather than a perpetual spinner.
 */
export function bucketTree(nodes: FileNode[]): Map<string, FileNode[]> {
  const map = new Map<string, FileNode[]>([["", []]]);
  const bucket = (dir: string): FileNode[] => {
    let arr = map.get(dir);
    if (!arr) {
      arr = [];
      map.set(dir, arr);
    }
    return arr;
  };
  for (const n of nodes) {
    bucket(parentDir(n.path)).push(n);
    if (n.isDir) bucket(n.path);
  }
  for (const arr of map.values()) sortNodes(arr);
  return map;
}

export interface FileTreeData {
  /** Direct children of a directory, or undefined if not loaded yet. */
  childrenOf: (dir: string) => FileNode[] | undefined;
  statusOf: (dir: string) => DirStatus | undefined;
  /** Load a directory's children if not already loaded/loading (lazy sources). */
  ensureDir: (dir: string) => void;
  /** Reload one directory — eager sources reload the whole tree. */
  reload: (dir: string) => void;
}

/**
 * The data layer behind {@link FileTree}, abstracting a source's two listing
 * styles behind one uniform read API (文件中枢统一 Step 0):
 *
 * - **eager** (`source.listTree` present, e.g. the server workspace): one
 *   recursive fetch buckets the whole tree into memory; every dir is `ready`,
 *   and reload re-fetches the lot. Natural for a small, server-enumerable space.
 * - **lazy** (`listDir` only, e.g. a local OS root): each directory loads on
 *   first expand; reload re-fetches just that level. Necessary for large trees.
 *
 * Either way the consumer just calls `childrenOf` / `ensureDir`; the rendering is
 * identical. Data lives in refs (mutated in place) with a version bump to
 * re-render, avoiding a fresh Map allocation per directory load.
 */
export function useFileTreeData(source: FileSource): FileTreeData {
  const eager = !!source.listTree;
  const childrenRef = useRef<Map<string, FileNode[]>>(new Map());
  const statusRef = useRef<Map<string, DirStatus>>(new Map());
  const [, bump] = useReducer((n: number) => n + 1, 0);

  const loadEager = useCallback(async () => {
    const listTree = source.listTree;
    if (!listTree) return;
    statusRef.current.set("", "loading");
    bump();
    try {
      const all = await listTree();
      childrenRef.current = bucketTree(all);
      const status = new Map<string, DirStatus>();
      for (const dir of childrenRef.current.keys()) status.set(dir, "ready");
      statusRef.current = status;
    } catch {
      statusRef.current = new Map([["", "error"]]);
    }
    bump();
  }, [source]);

  const loadDir = useCallback(
    async (dir: string) => {
      statusRef.current.set(dir, "loading");
      bump();
      try {
        childrenRef.current.set(dir, sortNodes(await source.listDir(dir)));
        statusRef.current.set(dir, "ready");
      } catch {
        statusRef.current.set(dir, "error");
      }
      bump();
    },
    [source],
  );

  // Reset + initial load whenever the source identity changes.
  useEffect(() => {
    childrenRef.current = new Map();
    statusRef.current = new Map();
    bump();
    if (eager) void loadEager();
    else void loadDir("");
  }, [eager, loadEager, loadDir]);

  const ensureDir = useCallback(
    (dir: string) => {
      if (eager) return; // whole tree already in memory
      if (statusRef.current.has(dir)) return; // loading / ready / error already
      void loadDir(dir);
    },
    [eager, loadDir],
  );

  const reload = useCallback(
    (dir: string) => {
      if (eager) void loadEager();
      else void loadDir(dir);
    },
    [eager, loadEager, loadDir],
  );

  // Stable readers (read live refs) + a memoized facade so effects/handlers can
  // depend on `data` without re-firing every render; identity changes only with
  // the source. Re-renders are driven by `bump`, so render-time reads stay fresh.
  const childrenOf = useCallback(
    (dir: string) => childrenRef.current.get(dir),
    [],
  );
  const statusOf = useCallback((dir: string) => statusRef.current.get(dir), []);

  return useMemo(
    () => ({ childrenOf, statusOf, ensureDir, reload }),
    [childrenOf, statusOf, ensureDir, reload],
  );
}
