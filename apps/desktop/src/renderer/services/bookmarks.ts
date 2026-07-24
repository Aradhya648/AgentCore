import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** One saved message in the「已收藏」view (`GET /v1/bookmarks`). */
export type BookmarkItem = Schemas["BookmarkItem"];
type BookmarkListResponse = Schemas["BookmarkListResponse"];
type BookmarkIdsResponse = Schemas["BookmarkIdsResponse"];

/** React Query key for the「已收藏」list (shared by the page + optimistic invalidation). */
export const BOOKMARKS_QUERY_KEY = ["bookmarks", "list"] as const;

/**
 * Bookmark a message (消息收藏 → 命令面板「已收藏」). Server-stored so it is reachable
 * from any device; idempotent server-side (re-adding returns the existing row).
 */
export async function addBookmark(
  conversationId: string,
  messageId: string,
): Promise<BookmarkItem> {
  return api.post<BookmarkItem>("/v1/bookmarks", {
    conversation_id: conversationId,
    message_id: messageId,
  });
}

/** Remove a message bookmark (idempotent — a no-match is still a success). */
export async function removeBookmark(messageId: string): Promise<void> {
  await api.delete(`/v1/bookmarks/${messageId}`);
}

/** The user's full「已收藏」list, newest-first (cross-device). */
export async function listBookmarks(): Promise<BookmarkItem[]> {
  const res = await api.get<BookmarkListResponse>("/v1/bookmarks");
  return res.data;
}

/** The bookmarked message ids within one conversation (star state on open). */
export async function listBookmarkIds(
  conversationId: string,
): Promise<string[]> {
  const res = await api.get<BookmarkIdsResponse>(
    `/v1/bookmarks/ids?conversation_id=${encodeURIComponent(conversationId)}`,
  );
  return res.message_ids;
}
