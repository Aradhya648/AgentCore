import { isWebPreview } from "@/lib/preview";
import { ApiError } from "@/services/api";
import { type AgentAuditListResponse, fetchTurnAudit } from "@/services/audit";
import { useEffect, useSyncExternalStore } from "react";

type TurnAuditEntry = {
  data: AgentAuditListResponse | null;
  loading: boolean;
  error: string | null;
};

const EMPTY: TurnAuditEntry = { data: null, loading: false, error: null };

const entries = new Map<string, TurnAuditEntry>();
const listeners = new Map<string, Set<() => void>>();
const inflight = new Map<string, Promise<void>>();

function cacheKey(conversationId: string, messageId: string): string {
  return `${conversationId}\0${messageId}`;
}

function notify(key: string): void {
  for (const listener of listeners.get(key) ?? []) listener();
}

function subscribe(key: string, onStoreChange: () => void): () => void {
  if (!listeners.has(key)) listeners.set(key, new Set());
  listeners.get(key)?.add(onStoreChange);
  return () => {
    listeners.get(key)?.delete(onStoreChange);
  };
}

function getSnapshot(key: string): TurnAuditEntry {
  return entries.get(key) ?? EMPTY;
}

function ensureLoad(conversationId: string, messageId: string): void {
  const key = cacheKey(conversationId, messageId);
  if (inflight.has(key)) return;

  entries.set(key, { ...getSnapshot(key), loading: true, error: null });
  notify(key);

  const promise = fetchTurnAudit(conversationId, messageId, {
    includeCausal: true,
  })
    .then((data) => {
      entries.set(key, { data, loading: false, error: null });
      notify(key);
    })
    .catch((e) => {
      // 404 = no audit rows yet (observe/workspace solo turns) — empty, not error.
      const empty = e instanceof ApiError && e.status === 404;
      entries.set(
        key,
        empty
          ? { data: { data: [], total: 0 }, loading: false, error: null }
          : { data: null, loading: false, error: "加载失败" },
      );
      notify(key);
    })
    .finally(() => {
      inflight.delete(key);
    });

  inflight.set(key, promise);
}

/** Drop cached turn audit and refetch (e.g. after appending an audit row). */
export function invalidateTurnAudit(
  conversationId: string,
  messageId: string,
): void {
  const key = cacheKey(conversationId, messageId);
  inflight.delete(key);
  entries.delete(key);
  notify(key);
  ensureLoad(conversationId, messageId);
}

export type TurnAuditState = TurnAuditEntry;

/**
 * Turn-scoped audit + causal graph, deduped per conversation/message pair.
 * Shared by run-detail sections and GraphView audit badges.
 */
export function useTurnAudit(
  conversationId: string | null,
  messageId: string | null,
): TurnAuditState {
  const preview = isWebPreview();
  const key =
    preview || !conversationId || !messageId
      ? ""
      : cacheKey(conversationId, messageId);

  useEffect(() => {
    if (!key || !conversationId || !messageId) return;
    ensureLoad(conversationId, messageId);
  }, [key, conversationId, messageId]);

  return useSyncExternalStore(
    (onStoreChange) => (key ? subscribe(key, onStoreChange) : () => {}),
    () => (key ? getSnapshot(key) : EMPTY),
    () => (key ? getSnapshot(key) : EMPTY),
  );
}

/** Test-only reset for module-level cache. */
export function resetTurnAuditCacheForTests(): void {
  entries.clear();
  listeners.clear();
  inflight.clear();
}
