import { isWebPreview } from "@/lib/preview";
import {
  type RunLlmWindowResponse,
  fetchRunLlmWindow,
} from "@/services/llmWindow";
import { useEffect, useSyncExternalStore } from "react";

type RunLlmWindowEntry = {
  data: RunLlmWindowResponse | null;
  loading: boolean;
  error: string | null;
};

const EMPTY: RunLlmWindowEntry = { data: null, loading: false, error: null };

const entries = new Map<string, RunLlmWindowEntry>();
const listeners = new Map<string, Set<() => void>>();
const inflight = new Map<string, Promise<void>>();

function cacheKey(
  conversationId: string,
  messageId: string,
  runId: string,
): string {
  return `${conversationId}\0${messageId}\0${runId}`;
}

function notify(key: string): void {
  for (const listener of listeners.get(key) ?? []) {
    listener();
  }
}

function subscribe(key: string, onStoreChange: () => void): () => void {
  if (!listeners.has(key)) listeners.set(key, new Set());
  const set = listeners.get(key);
  set?.add(onStoreChange);
  return () => {
    set?.delete(onStoreChange);
  };
}

function getSnapshot(key: string): RunLlmWindowEntry {
  return entries.get(key) ?? EMPTY;
}

function ensureLoad(
  conversationId: string,
  messageId: string,
  runId: string,
): void {
  const key = cacheKey(conversationId, messageId, runId);
  if (inflight.has(key)) return;

  entries.set(key, { ...getSnapshot(key), loading: true, error: null });
  notify(key);

  const promise = fetchRunLlmWindow(conversationId, messageId, runId)
    .then((data) => {
      entries.set(key, { data, loading: false, error: null });
      notify(key);
    })
    .catch(() => {
      entries.set(key, { data: null, loading: false, error: "加载失败" });
      notify(key);
    })
    .finally(() => {
      inflight.delete(key);
    });

  inflight.set(key, promise);
}

export type RunLlmWindowState = RunLlmWindowEntry;

/**
 * Run-scoped LLM window fold, deduped per conversation/message/run triple.
 * Gated by diagnostic mode at the call site — not fetched when the panel is hidden.
 */
export function useRunLlmWindow(
  conversationId: string | null,
  messageId: string | null,
  runId: string | null,
  enabled: boolean,
): RunLlmWindowState {
  const preview = isWebPreview();
  const key =
    preview || !enabled || !conversationId || !messageId || !runId
      ? ""
      : cacheKey(conversationId, messageId, runId);

  useEffect(() => {
    if (!key || !conversationId || !messageId || !runId) return;
    ensureLoad(conversationId, messageId, runId);
  }, [key, conversationId, messageId, runId]);

  return useSyncExternalStore(
    (onStoreChange) => (key ? subscribe(key, onStoreChange) : () => {}),
    () => (key ? getSnapshot(key) : EMPTY),
    () => (key ? getSnapshot(key) : EMPTY),
  );
}

/** Test-only reset for module-level cache. */
export function resetRunLlmWindowCacheForTests(): void {
  entries.clear();
  listeners.clear();
  inflight.clear();
}
