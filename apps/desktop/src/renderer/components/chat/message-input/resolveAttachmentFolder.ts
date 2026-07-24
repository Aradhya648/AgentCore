import { getConversations } from "@/hooks/useConversations";
import { getFolders } from "@/hooks/useFolders";
import type { IndexedEntry } from "@/lib/fileIndex";

const WORKSPACE_FOLDER_PREFIX = "workspace:folder:";

/**
 * Infer a folder (project) id from an @-mention / browse attachment entry.
 * Returns null when the entry has no mappable project (e.g. bare local root).
 */
export function resolveFolderFromIndexedEntry(
  entry: IndexedEntry,
): { folderId: string; folderName: string } | null {
  if (entry.kind === "conversation") {
    const conv = getConversations().find((c) => c.id === entry.relPath);
    if (!conv?.folderId) return null;
    const folder = getFolders().find((f) => f.id === conv.folderId);
    return folder
      ? { folderId: folder.id, folderName: folder.name }
      : { folderId: conv.folderId, folderName: entry.name };
  }

  if (entry.sourceId.startsWith(WORKSPACE_FOLDER_PREFIX)) {
    const folderId = entry.sourceId.slice(WORKSPACE_FOLDER_PREFIX.length);
    if (!folderId) return null;
    const folder = getFolders().find((f) => f.id === folderId);
    return folder
      ? { folderId: folder.id, folderName: folder.name }
      : { folderId, folderName: entry.sourceLabel };
  }

  const localMatch = /^local:([^:]+)/.exec(entry.sourceId);
  if (localMatch) {
    const rootId = localMatch[1];
    const folder = getFolders().find(
      (f) => f.mode === "local" && f.localRootId === rootId,
    );
    return folder ? { folderId: folder.id, folderName: folder.name } : null;
  }

  return null;
}
