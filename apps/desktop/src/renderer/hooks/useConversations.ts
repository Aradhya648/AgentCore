import {
  patchConversationScratch,
  removeConversationScratch,
} from "@/hooks/useWorkspaces";
import { clearConversationUiState } from "@/lib/clearConversationUiState";
import { purgeConversationRuntimeState } from "@/lib/purgeConversationRuntimeState";
import { queryClient } from "@/lib/queryClient";
import { conversationKeys, workspaceKeys } from "@/lib/queryKeys";
import {
  deleteConversation as apiDeleteConversation,
  duplicateConversation as apiDuplicateConversation,
  renameConversation as apiRenameConversation,
  setConversationArchived as apiSetArchived,
  setConversationPinned as apiSetPinned,
  listConversations,
  listGrouped,
} from "@/services/conversations";
import type { FolderMeta } from "@/services/folders";
import type { Conversation } from "@/stores/conversation";
import { useMutation, useQuery } from "@tanstack/react-query";

/**
 * The conversation list as React Query data (REST 数据层 — the reference slice).
 *
 * `/v1/conversations/grouped` returns folders + conversations in one trip, so the
 * cached value keeps both halves; conversation consumers read the `conversations`
 * half via {@link useConversations}, and the shell seeds the folders store from
 * the `folders` half (folder CRUD still lives in its own store for now).
 *
 * The list is loaded once and then driven optimistically (mirroring the prior
 * hydrate-once + optimistic-mutation model), so it never refetches under the
 * user. The imperative cache helpers below let non-React callers (the SSE turn
 * pipeline, the composer) mutate that same cache.
 */
export interface GroupedConversations {
  folders: FolderMeta[];
  conversations: Conversation[];
}

/** Stable empty list so a component without data keeps a constant reference. */
const EMPTY_CONVERSATIONS: Conversation[] = [];

function readGrouped(): GroupedConversations {
  return (
    queryClient.getQueryData<GroupedConversations>(
      conversationKeys.grouped,
    ) ?? {
      folders: [],
      conversations: [],
    }
  );
}

/** Imperative read of the cached conversation list (for non-React callers). */
export function getConversations(): Conversation[] {
  return readGrouped().conversations;
}

/** Rewrite the cached conversation list, leaving the folders half untouched. */
function writeConversations(
  updater: (list: Conversation[]) => Conversation[],
): void {
  queryClient.setQueryData<GroupedConversations>(
    conversationKeys.grouped,
    (old) => {
      const base = old ?? { folders: [], conversations: [] };
      return { ...base, conversations: updater(base.conversations) };
    },
  );
}

/** Prepend a conversation (or move an existing one to the front, deduped). */
export function upsertConversationFront(conv: Conversation): void {
  writeConversations((list) => [conv, ...list.filter((c) => c.id !== conv.id)]);
}

/** Drop a conversation from the cached list. */
export function removeConversationFromCache(id: string): void {
  writeConversations((list) => list.filter((c) => c.id !== id));
}

/** Shallow-merge a patch onto one cached conversation (no-op if absent). */
export function patchConversationCache(
  id: string,
  patch: Partial<Conversation>,
): void {
  writeConversations((list) =>
    list.map((c) => (c.id === id ? { ...c, ...patch } : c)),
  );
}

/** Move a conversation to the top and stamp `updatedAt = now` (a turn bumps it
 * into the「今天」group like the backend ordering will on the next reload). */
export function bumpConversationCache(id: string): void {
  writeConversations((list) => {
    const target = list.find((c) => c.id === id);
    if (!target) return list;
    return [
      { ...target, updatedAt: new Date().toISOString() },
      ...list.filter((c) => c.id !== id),
    ];
  });
}

/** Undo an optimistic {@link bumpConversationCache}: put the conversation back
 * at `index` and restore its `updatedAt`. */
export function restoreConversationCache(
  id: string,
  index: number,
  updatedAt: string,
): void {
  writeConversations((list) => {
    const target = list.find((c) => c.id === id);
    if (!target) return list;
    const without = list.filter((c) => c.id !== id);
    const at = Math.max(0, Math.min(index, without.length));
    return [
      ...without.slice(0, at),
      { ...target, updatedAt },
      ...without.slice(at),
    ];
  });
}

/** The grouped folders+conversations query — the single network source for the
 * sidebar / conversations list. Loaded once, then optimistic. */
export function useGroupedConversations() {
  return useQuery({
    queryKey: conversationKeys.grouped,
    queryFn: listGrouped,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
  });
}

/** Reactive conversation list (server-ordered; consumers re-sort by recency). */
export function useConversations(): Conversation[] {
  return useGroupedConversations().data?.conversations ?? EMPTY_CONVERSATIONS;
}

/** Persist a title rename, optimistic with rollback on failure. */
export function useRenameConversation() {
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiRenameConversation(id, title),
    onMutate: ({ id, title }) => {
      const prev = getConversations().find((c) => c.id === id)?.title ?? null;
      patchConversationCache(id, { title });
      // Keep the files-hub rail label in sync when that cache is warm.
      patchConversationScratch(id, { name: title });
      return { id, prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev != null) {
        patchConversationCache(ctx.id, { title: ctx.prev });
        patchConversationScratch(ctx.id, { name: ctx.prev });
      }
    },
  });
}

/** Soft-delete a conversation server-side, then drop it from the cache (delete
 * first so a failed delete leaves the row in place). */
export function useDeleteConversation() {
  return useMutation({
    mutationFn: (id: string) => apiDeleteConversation(id),
    onSuccess: (_data, id) => {
      removeConversationFromCache(id);
      // Purge this conversation's persisted UI prefs (disclosure / drafts /
      // views / canvas-turn / graph-fold) so blob maps don't leak keys for gone
      // conversations (守「表恒收敛不膨胀」).
      clearConversationUiState(id);
      // Drop the files-hub rail section + refetch so open tabs close via
      // FileWorkbench's「workspace gone → close tabs」effect.
      removeConversationScratch(id);
      // In-memory runtime buckets (pausedTurns / interactions / turnModel /
      // backgroundTasks / processes / terminals / toolOutput).
      purgeConversationRuntimeState(id);
      void queryClient.invalidateQueries({ queryKey: workspaceKeys.list });
    },
  });
}

/** Clone a conversation into a new one carrying a copy of its transcript (克隆对话).
 * Server-first (the copy only exists once the backend commits it); on success the
 * returned row is prepended to the sidebar cache so it appears at the top, and the
 * caller navigates into it. */
export function useDuplicateConversation() {
  return useMutation({
    mutationFn: (id: string) => apiDuplicateConversation(id),
    onSuccess: (conv) => upsertConversationFront(conv),
  });
}

/** Pin / unpin a conversation (置顶对话), optimistic with rollback on failure.
 * Lists re-sort pinned-first, so the row jumps to / from the top immediately. */
export function useTogglePin() {
  return useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      apiSetPinned(id, pinned),
    onMutate: ({ id, pinned }) => {
      const prev = getConversations().find((c) => c.id === id)?.pinned ?? false;
      patchConversationCache(id, { pinned });
      return { id, prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx) patchConversationCache(ctx.id, { pinned: ctx.prev });
    },
  });
}

/** Archive a conversation (归档对话): hide it from the live list. Server-first
 * (like delete) so a failed call leaves the row in place; on success drop it from
 * the live cache and refresh the「已归档」view. */
export function useArchiveConversation() {
  return useMutation({
    mutationFn: (id: string) => apiSetArchived(id, true),
    onSuccess: (_data, id) => {
      removeConversationFromCache(id);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.archived,
      });
    },
  });
}

/** Unarchive a conversation (取消归档): return it to the live list. Optimistically
 * drop it from the「已归档」view so the row leaves at once; on success put the
 * returned (now-live) row back into the grouped cache; on failure refetch the
 * archived list to restore the row. */
export function useUnarchiveConversation() {
  return useMutation({
    mutationFn: (id: string) => apiSetArchived(id, false),
    onMutate: (id) => {
      queryClient.setQueryData<Conversation[]>(
        conversationKeys.archived,
        (old) => (old ? old.filter((c) => c.id !== id) : old),
      );
    },
    onSuccess: (conv) => upsertConversationFront(conv),
    onError: () => {
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.archived,
      });
    },
  });
}

/** The「已归档」conversation list — a separate on-demand query (not the live
 * grouped cache, which excludes archived rows). Pass `enabled` so it only fetches
 * when the archived view is actually shown. */
export function useArchivedConversations(enabled: boolean) {
  return useQuery({
    queryKey: conversationKeys.archived,
    queryFn: () => listConversations(true),
    enabled,
    staleTime: 30_000,
  });
}
