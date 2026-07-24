import { type Capabilities, getCapabilities } from "@/services/capabilities";
import { useCallback, useEffect, useState } from "react";

export type CapabilitiesStatus = "loading" | "error" | "ready";

// Module-level cache so the 能力 sub-pages (工具 / AI 提示词) share a
// single /v1/capabilities fetch — navigating between them renders instantly from cache
// instead of re-fetching and flashing a spinner. The catalog is effectively static for
// the session; `reload(true)` forces a refresh after an error.
let cache: Capabilities | null = null;
let inflight: Promise<Capabilities> | null = null;

type CacheListener = (data: Capabilities) => void;
const listeners = new Set<CacheListener>();

function notifyListeners(): void {
  if (!cache) return;
  for (const listener of listeners) listener(cache);
}

function fetchCapabilities(force: boolean): Promise<Capabilities> {
  if (!force && cache) return Promise.resolve(cache);
  if (inflight) return inflight;
  inflight = getCapabilities()
    .then((res) => {
      cache = res;
      notifyListeners();
      return res;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** Test-only: clear the module cache between cases. */
export function __resetCapabilitiesCacheForTests(): void {
  cache = null;
  inflight = null;
  listeners.clear();
}

/** Shared loader for the capability catalog (tools + skills + guidelines). Returns the
 * cached result immediately when available, otherwise tracks loading/error. */
export function useCapabilities() {
  const [data, setData] = useState<Capabilities | null>(cache);
  const [status, setStatus] = useState<CapabilitiesStatus>(
    cache ? "ready" : "loading",
  );

  const load = useCallback((force = false) => {
    let cancelled = false;
    if (force || !cache) setStatus("loading");
    fetchCapabilities(force)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), [load]);

  // Stay in sync when another mount refreshes the cache.
  useEffect(() => {
    const onCache = (next: Capabilities) => {
      setData(next);
      setStatus("ready");
    };
    listeners.add(onCache);
    return () => {
      listeners.delete(onCache);
    };
  }, []);

  return { data, status, reload: () => load(true) };
}
