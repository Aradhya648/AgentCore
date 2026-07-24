import { useConversations } from "@/hooks/useConversations";
import { useFolders } from "@/hooks/useFolders";
import type { FolderMeta } from "@/services/folders";
import type { Conversation } from "@/stores/conversation";
import { useMemo } from "react";

/** Workspaces (folders) shown in the rail before deferring to /conversations. */
export const MAX_WORKSPACE_GROUPS = 6;

/** One sidebar「项目」group: a folder plus its (recency-sorted) conversations. */
export interface WorkspaceGroup {
  folder: FolderMeta;
  /** This folder's conversations, pinned-first then newest-first. */
  convs: Conversation[];
  /** Newest `updatedAt` in `convs` (ms epoch), for ordering groups by activity. */
  latest: number;
}

/** Pinned float to the top (置顶对话); within each group, newest activity first. */
function byPinnedThenRecency(a: Conversation, b: Conversation): number {
  if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
  return (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0);
}

/**
 * Partition conversations into「项目」groups (前端UX §一 方案B): folder → its
 * conversations (pinned-first, newest-first), groups ordered by latest activity and
 * capped at {@link MAX_WORKSPACE_GROUPS}. Pure (no React) so it's unit-testable; the
 * {@link useWorkspaceGroups} hook just memoizes it over the live cache.
 *
 * **裸聊 (folderless chats) are excluded** — under 方案B they live solely in「快速对话」
 * (干净二分零重复). Conversations whose folder isn't in `folders` (e.g. mid-deletion)
 * are skipped; the delete flow unbinds them to 裸聊 so they resurface in「快速对话」.
 */
export function buildWorkspaceGroups(
  conversations: Conversation[],
  folders: FolderMeta[],
): WorkspaceGroup[] {
  const byFolder = new Map<string, Conversation[]>();
  for (const c of conversations) {
    if (!c.folderId) continue; // 裸聊 — belongs to「快速对话」, not a group
    const arr = byFolder.get(c.folderId);
    if (arr) arr.push(c);
    else byFolder.set(c.folderId, [c]);
  }
  const folderById = new Map(folders.map((f) => [f.id, f]));
  const result: WorkspaceGroup[] = [];
  for (const [folderId, convs] of byFolder) {
    const folder = folderById.get(folderId);
    if (!folder) continue; // folder not in cache (e.g. just deleted) — skip
    convs.sort(byPinnedThenRecency);
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
 * `WorkspaceGroups` (renders them) and `RecentConversations` (bare-chat zone below)
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
