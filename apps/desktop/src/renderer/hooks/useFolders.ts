import type { GroupedConversations } from "@/hooks/useConversations";
import {
  getConversations,
  removeConversationFromCache,
  useGroupedConversations,
} from "@/hooks/useConversations";
import { queryClient } from "@/lib/queryClient";
import { conversationKeys } from "@/lib/queryKeys";
import {
  type CreateFolderInput,
  type FolderMeta,
  createFolder,
  deleteFolder,
  permanentDeleteFolder,
  updateFolder,
} from "@/services/folders";
import { useMutation } from "@tanstack/react-query";

/**
 * Folders as React Query data — folders share the `/grouped` query (and its
 * cache entry) with conversations, so this reads/writes the `folders` half of
 * that same entry. Pure-UI folder state (pending rename, draft workspace intent)
 * stays in the zustand folders store; only the server-owned list lives here.
 */
const EMPTY_FOLDERS: FolderMeta[] = [];

/** Imperative read of the cached folder list (for non-React callers). */
export function getFolders(): FolderMeta[] {
  return (
    queryClient.getQueryData<GroupedConversations>(conversationKeys.grouped)
      ?.folders ?? []
  );
}

/** Rewrite the cached folder list, leaving the conversations half untouched. */
function writeFolders(updater: (list: FolderMeta[]) => FolderMeta[]): void {
  queryClient.setQueryData<GroupedConversations>(
    conversationKeys.grouped,
    (old) => {
      const base = old ?? { folders: [], conversations: [] };
      return { ...base, folders: updater(base.folders) };
    },
  );
}

/** Prepend a folder (newest first, before the server reorders on reload). */
export function addFolderCache(folder: FolderMeta): void {
  writeFolders((list) => [folder, ...list.filter((f) => f.id !== folder.id)]);
}

/** Shallow-merge a patch onto one cached folder (no-op if absent). */
export function patchFolderCache(id: string, patch: Partial<FolderMeta>): void {
  writeFolders((list) =>
    list.map((f) => (f.id === id ? { ...f, ...patch } : f)),
  );
}

/** Drop a folder from the cached list. */
export function removeFolderFromCache(id: string): void {
  writeFolders((list) => list.filter((f) => f.id !== id));
}

/** Reactive folder list (server-ordered). */
export function useFolders(): FolderMeta[] {
  return useGroupedConversations().data?.folders ?? EMPTY_FOLDERS;
}

/** Create a project (= workspace), then add it to the cache. */
export function useCreateFolder() {
  return useMutation({
    mutationFn: (input: CreateFolderInput) => createFolder(input),
    onSuccess: (folder) => {
      addFolderCache(folder);
    },
  });
}

/** Rename a folder, optimistic with rollback on failure. */
export function useUpdateFolder() {
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { name?: string } }) =>
      updateFolder(id, patch),
    onMutate: ({ id, patch }) => {
      const prev = getFolders().find((f) => f.id === id) ?? null;
      const cachePatch: Partial<FolderMeta> = {};
      if (patch.name !== undefined) cachePatch.name = patch.name;
      patchFolderCache(id, cachePatch);
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) {
        patchFolderCache(ctx.prev.id, { name: ctx.prev.name });
      }
    },
  });
}

/**
 * Soft-delete a folder. Server archives member conversations (不解组);
 * drop the folder from cache and refresh conversation lists.
 */
export function useDeleteFolder() {
  return useMutation({
    mutationFn: (id: string) => deleteFolder(id),
    onSuccess: (_data, id) => {
      removeFolderFromCache(id);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.grouped,
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.archived,
      });
    },
  });
}

/** 彻底删除项目 — hard-delete folder and all member chats. */
export function usePermanentDeleteFolder() {
  return useMutation({
    mutationFn: (id: string) => permanentDeleteFolder(id),
    onSuccess: (_data, id) => {
      for (const c of getConversations()) {
        if (c.folderId === id) removeConversationFromCache(c.id);
      }
      removeFolderFromCache(id);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.archived,
      });
    },
  });
}
