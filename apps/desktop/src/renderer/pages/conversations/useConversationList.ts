import {
  useArchivedConversations,
  useConversations,
} from "@/hooks/useConversations";
import { useFolders } from "@/hooks/useFolders";
import { UNGROUPED_KEY } from "@/stores/folders";
import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  ALL_KEY,
  ARCHIVED_KEY,
  EMPTY_CONVERSATIONS,
  STALE_DAYS,
  byPinnedThenRecency,
} from "./constants";

/**
 * Left-pane filter selection + deep-link routing from global search / CommandPalette.
 */
export function useConversationRouting() {
  const location = useLocation();
  const folders = useFolders();

  const [selected, setSelected] = useState<string>(ALL_KEY);
  const [flashId, setFlashId] = useState<string | null>(null);

  const folderIds = useMemo(() => new Set(folders.map((f) => f.id)), [folders]);

  // A folder hit from global search jumps here via navigation state.
  // biome-ignore lint/correctness/useExhaustiveDependencies: location.key is the intentional per-navigation trigger.
  useEffect(() => {
    const state = location.state as {
      focusFolderId?: string;
      focusArchived?: boolean;
    } | null;
    if (state?.focusArchived) {
      setSelected(ARCHIVED_KEY);
      return;
    }
    const target = state?.focusFolderId;
    if (!target) return;
    setSelected(target);
    setFlashId(target);
    const t = setTimeout(() => setFlashId(null), 1500);
    return () => clearTimeout(t);
  }, [location.key]);

  // Deleted folder → fall back to 全部对话.
  useEffect(() => {
    if (
      selected === ALL_KEY ||
      selected === UNGROUPED_KEY ||
      selected === ARCHIVED_KEY
    ) {
      return;
    }
    if (!folderIds.has(selected)) setSelected(ALL_KEY);
  }, [folderIds, selected]);

  return { selected, setSelected, flashId, folderIds, folders };
}

/**
 * Right-pane list: search, stale filter, folder scoping, per-folder counts.
 */
export function useConversationList(selected: string, folderIds: Set<string>) {
  const conversations = useConversations();
  const [query, setQuery] = useState("");
  const [staleOnly, setStaleOnly] = useState(false);

  const isArchivedView = selected === ARCHIVED_KEY;
  const archivedQuery = useArchivedConversations(true);
  const archived = archivedQuery.data ?? EMPTY_CONVERSATIONS;

  const counts = useMemo(() => {
    let ungrouped = 0;
    const perFolder = new Map<string, number>();
    for (const c of conversations) {
      const fid = c.folderId;
      if (fid && folderIds.has(fid))
        perFolder.set(fid, (perFolder.get(fid) ?? 0) + 1);
      else ungrouped += 1;
    }
    return { ungrouped, perFolder };
  }, [conversations, folderIds]);

  const list = useMemo(() => {
    const base = isArchivedView
      ? archived
      : conversations.filter((c) => {
          if (selected === ALL_KEY) return true;
          if (selected === UNGROUPED_KEY)
            return !c.folderId || !folderIds.has(c.folderId);
          return c.folderId === selected;
        });
    const q = query.trim().toLowerCase();
    let filtered = q
      ? base.filter((c) => c.title.toLowerCase().includes(q))
      : base;
    if (staleOnly && !isArchivedView) {
      const cutoff = Date.now() - STALE_DAYS * 86_400_000;
      filtered = filtered.filter(
        (c) => (Date.parse(c.updatedAt) || 0) < cutoff,
      );
    }
    return [...filtered].sort(byPinnedThenRecency);
  }, [
    conversations,
    archived,
    isArchivedView,
    selected,
    query,
    folderIds,
    staleOnly,
  ]);

  return {
    conversations,
    archived,
    counts,
    list,
    query,
    setQuery,
    staleOnly,
    setStaleOnly,
    isArchivedView,
  };
}
