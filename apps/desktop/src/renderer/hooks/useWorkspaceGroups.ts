import { useConversations } from "@/hooks/useConversations";
import { useFolders } from "@/hooks/useFolders";
import {
  type FolderMeta,
  dedupeFoldersByLocalBinding,
  localFolderBindingKey,
} from "@/services/folders";
import type { Conversation } from "@/stores/conversation";
import { useMemo } from "react";

/** Workspaces (folders) shown in the rail before deferring to /conversations. */
export const MAX_WORKSPACE_GROUPS = 6;

/** One sidebar「项目」group: a folder plus its (recency-sorted) conversations. */
export interface WorkspaceGroup {
  folder: FolderMeta;
  /**
   * Every live conversation in this folder (incl. pinned), newest-first.
   * Header actions (归档全部 / 删项目) need the full set; the rail list filters
   * pinned out so they only appear in the 置顶区.
   */
  convs: Conversation[];
  /** Newest `updatedAt` in `convs` (ms epoch), for ordering groups by activity. */
  latest: number;
}

function byRecency(a: Conversation, b: Conversation): number {
  return (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0);
}

/**
 * Partition conversations into「项目」groups (前端UX §一 方案C): folder → its
 * conversations (newest-first; pinned included for header/latest), groups ordered
 * by latest activity and capped at {@link MAX_WORKSPACE_GROUPS}. Pure (no React)
 * so it's unit-testable; the {@link useWorkspaceGroups} hook just memoizes it.
 *
 * **裸聊 (folderless chats) are excluded** — they live in「快速对话」. Pinned
 * foldered chats stay in `convs` for group actions but the rail renders them only
 * in the 置顶区 (零重复). Conversations whose folder isn't in `folders` (e.g.
 * mid-deletion) are skipped; the delete flow unbinds them to 裸聊 so they
 * resurface in「快速对话」.
 *
 * Map each folder id → the canonical (first / oldest) id for its local binding
 * lives in {@link canonicalFolderIds}: cloud folders map to themselves so
 * sidebar groups don't duplicate the same local path when historical duplicate
 * rows exist.
 */
function canonicalFolderIds(folders: FolderMeta[]): Map<string, string> {
  const keptByBinding = new Map<string, string>();
  const canonical = new Map<string, string>();
  for (const f of folders) {
    if (f.mode === "local" && f.localRootId) {
      const key = localFolderBindingKey(f.localRootId, f.localSubpath);
      const kept = keptByBinding.get(key);
      if (kept) {
        canonical.set(f.id, kept);
      } else {
        keptByBinding.set(key, f.id);
        canonical.set(f.id, f.id);
      }
    } else {
      canonical.set(f.id, f.id);
    }
  }
  return canonical;
}

export function buildWorkspaceGroups(
  conversations: Conversation[],
  folders: FolderMeta[],
): WorkspaceGroup[] {
  const displayFolders = dedupeFoldersByLocalBinding(folders);
  const canonical = canonicalFolderIds(folders);
  const byFolder = new Map<string, Conversation[]>();
  for (const c of conversations) {
    if (!c.folderId) continue; // 裸聊 — belongs to「快速对话」, not a group
    const folderId = canonical.get(c.folderId) ?? c.folderId;
    const arr = byFolder.get(folderId);
    if (arr) arr.push(c);
    else byFolder.set(folderId, [c]);
  }
  const folderById = new Map(displayFolders.map((f) => [f.id, f]));
  const result: WorkspaceGroup[] = [];
  for (const [folderId, convs] of byFolder) {
    const folder = folderById.get(folderId);
    if (!folder) continue; // folder not in cache (e.g. just deleted) — skip
    convs.sort(byRecency);
    const latest = convs.reduce(
      (m, c) => Math.max(m, Date.parse(c.updatedAt) || 0),
      0,
    );
    result.push({ folder, convs, latest });
  }
  result.sort((a, b) => b.latest - a.latest);
  return result.slice(0, MAX_WORKSPACE_GROUPS);
}

/**
 * The sidebar's「项目」groups over the live grouped cache. Shared by
 * `WorkspaceGroups` (renders them) and `RecentConversations` (bare-chat zone)
 * so the partition lives in one place.
 */
export function useWorkspaceGroups(): WorkspaceGroup[] {
  const conversations = useConversations();
  const folders = useFolders();
  return useMemo(
    () => buildWorkspaceGroups(conversations, folders),
    [conversations, folders],
  );
}
