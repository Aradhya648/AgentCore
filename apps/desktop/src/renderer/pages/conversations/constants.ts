import type { Conversation } from "@/stores/conversation";
import { UNGROUPED_KEY } from "@/stores/folders";

/** Synthetic left-pane filter key for「全部对话」(not a real folder). */
export const ALL_KEY = "__all__";
/** Synthetic left-pane filter key for the「已归档」view (归档对话). */
export const ARCHIVED_KEY = "__archived__";

/** Stable empty list so the archived view keeps a constant reference until data. */
export const EMPTY_CONVERSATIONS: Conversation[] = [];

/** Days without activity for the「久未活跃」quick filter on the management page. */
export const STALE_DAYS = 30;

export function byPinnedThenRecency(a: Conversation, b: Conversation): number {
  if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
  return (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0);
}

export function activeFilterName(
  selected: string,
  folders: { id: string; name: string }[],
): string {
  if (selected === ALL_KEY) return "全部对话";
  if (selected === UNGROUPED_KEY) return "未分组";
  if (selected === ARCHIVED_KEY) return "已归档";
  return folders.find((f) => f.id === selected)?.name ?? "全部对话";
}

export function isRealFolderFilter(
  selected: string,
  folderIds: Set<string>,
): boolean {
  return (
    selected !== ALL_KEY &&
    selected !== UNGROUPED_KEY &&
    selected !== ARCHIVED_KEY &&
    folderIds.has(selected)
  );
}

/** Navigation options for `/files` when jumping from a folder/project context. */
export function filesFocusState(
  conversationId: string | null | undefined,
  folderId?: string | null,
): { state: { focusWsId: string } } | undefined {
  if (folderId) return { state: { focusWsId: `folder:${folderId}` } };
  if (!conversationId) return undefined;
  return { state: { focusWsId: `conv:${conversationId}` } };
}

export function firstConversationInFolder(
  conversations: Conversation[],
  folderId: string,
): Conversation | undefined {
  return conversations
    .filter((c) => c.folderId === folderId)
    .sort(byPinnedThenRecency)[0];
}

export function newChatFolderTarget(
  selected: string,
  folderIds: Set<string>,
): string | null {
  if (
    selected !== ALL_KEY &&
    selected !== UNGROUPED_KEY &&
    folderIds.has(selected)
  ) {
    return selected;
  }
  return null;
}
