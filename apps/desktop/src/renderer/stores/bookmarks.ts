import { queryClient } from "@/lib/queryClient";
import { notifyError } from "@/lib/toast";
import {
  BOOKMARKS_QUERY_KEY,
  addBookmark,
  listBookmarkIds,
  removeBookmark,
} from "@/services/bookmarks";
import { create } from "zustand";

/**
 * 消息收藏 star-state store (方向 4).
 *
 * Holds the set of the *currently-viewed* conversation's bookmarked message ids so
 * each assistant bubble can render its star. Hydrated on conversation open from the
 * server (跨设备 truth), then driven optimistically by {@link toggle}. The full
 * 「已收藏」list is a separate React Query (CommandPalette) — this store is purely the
 * lightweight per-conversation star state; a successful toggle invalidates that
 * query so the command-palette list stays in sync.
 */
interface BookmarkState {
  /** message ids known to be bookmarked (for the open conversation). */
  ids: Set<string>;
  /** Load the given conversation's bookmarked ids, replacing the current set. */
  hydrateForConversation: (conversationId: string) => Promise<void>;
  /** Toggle a message's bookmark, optimistic with rollback + toast on failure. */
  toggle: (conversationId: string, messageId: string) => Promise<void>;
}

export const useBookmarkStore = create<BookmarkState>((set, get) => ({
  ids: new Set<string>(),

  hydrateForConversation: async (conversationId) => {
    try {
      const ids = await listBookmarkIds(conversationId);
      set({ ids: new Set(ids) });
    } catch {
      // Best-effort: a failed load just leaves stars unfilled until next open.
    }
  },

  toggle: async (conversationId, messageId) => {
    const had = get().ids.has(messageId);
    // Optimistic flip so the star responds immediately.
    set((s) => {
      const next = new Set(s.ids);
      if (had) next.delete(messageId);
      else next.add(messageId);
      return { ids: next };
    });
    try {
      if (had) await removeBookmark(messageId);
      else await addBookmark(conversationId, messageId);
      // Keep the「已收藏」list fresh after a successful change.
      void queryClient.invalidateQueries({ queryKey: BOOKMARKS_QUERY_KEY });
    } catch (err) {
      // Revert to the prior state on a failed persist.
      set((s) => {
        const next = new Set(s.ids);
        if (had) next.add(messageId);
        else next.delete(messageId);
        return { ids: next };
      });
      notifyError(err, had ? "取消收藏失败" : "收藏失败");
    }
  },
}));
