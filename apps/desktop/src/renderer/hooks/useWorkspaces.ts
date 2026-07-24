import { getConversations } from "@/hooks/useConversations";
import { getFolders } from "@/hooks/useFolders";
import { queryClient } from "@/lib/queryClient";
import { workspaceKeys } from "@/lib/queryKeys";
import { bareConversationScratchSubpath } from "@/services/bareScratchPath";
import { type WorkspaceInfo, listWorkspaces } from "@/services/workspaces";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

/**
 * The user's workspaces as React Query data — `GET /v1/workspaces` may include
 * `folder:<id>` (project shared space) and `conv:<id>` (bare scratch).
 */
export function useWorkspaces() {
  return useQuery({
    queryKey: workspaceKeys.list,
    queryFn: listWorkspaces,
    staleTime: 30_000,
  });
}

/**
 * Workspace backing a conversation's side panel.
 * Project chats → `folder:<folderId>` (or synthesize from folder meta);
 * bare chats → `conv:<id>`.
 */
export function useConversationWorkspace(
  conversationId: string | null,
): WorkspaceInfo | null {
  const { data: workspaces } = useWorkspaces();
  return useMemo(() => {
    if (!conversationId) return null;
    const conv =
      getConversations().find((c) => c.id === conversationId) ?? null;
    if (conv?.folderId) {
      const listed = workspaces?.find(
        (w) => w.wsId === `folder:${conv.folderId}`,
      );
      if (listed) return listed;
      const folder = getFolders().find((f) => f.id === conv.folderId);
      if (!folder) return null;
      if (folder.mode === "local" && folder.localRootId) {
        return {
          wsId: `folder:${folder.id}`,
          name: folder.name,
          location: "local",
          rootId: folder.localRootId,
          subpath: folder.localSubpath ?? "",
          hasFiles: true,
        };
      }
      return {
        wsId: `folder:${folder.id}`,
        name: folder.name,
        location: "cloud",
        rootId: null,
        subpath: "",
        hasFiles: true,
      };
    }
    const wsId = `conv:${conversationId}`;
    const listed = workspaces?.find((w) => w.wsId === wsId) ?? null;
    if (!listed) return null;
    // 服务端尚未写回隔离 subpath、或列表仍空串时，容器根裸聊补齐契约路径。
    const sub = (listed.subpath ?? "").replace(/^\/+|\/+$/g, "");
    if (
      !sub &&
      listed.location === "local" &&
      listed.rootId &&
      conv?.localContainerRootId &&
      listed.rootId === conv.localContainerRootId
    ) {
      return {
        ...listed,
        subpath: bareConversationScratchSubpath(conversationId),
      };
    }
    return listed;
  }, [conversationId, workspaces]);
}

/** Rewrite the cached workspace list *iff* it's already loaded. */
function writeWorkspaces(
  updater: (list: WorkspaceInfo[]) => WorkspaceInfo[],
): void {
  const cur = queryClient.getQueryData<WorkspaceInfo[]>(workspaceKeys.list);
  if (!cur) return;
  queryClient.setQueryData<WorkspaceInfo[]>(workspaceKeys.list, updater(cur));
}

/** Reflect a newly surfaced conversation scratch into the rail (newest first). */
export function addConversationScratch(ws: WorkspaceInfo): void {
  writeWorkspaces((list) => [ws, ...list.filter((w) => w.wsId !== ws.wsId)]);
}

/** Reflect a conversation rename or binding change onto its rail item.
 * Missing `conv:<id>` → insert (bind-after-cloud has no prior rail row). */
export function patchConversationScratch(
  conversationId: string,
  patch: Partial<
    Pick<WorkspaceInfo, "name" | "rootId" | "subpath" | "location" | "hasFiles">
  >,
): void {
  const wsId = `conv:${conversationId}`;
  writeWorkspaces((list) => {
    const existing = list.find((w) => w.wsId === wsId);
    if (existing) {
      return list.map((w) => (w.wsId === wsId ? { ...w, ...patch } : w));
    }
    // Title comes from callers (bind path); avoid getConversations here to keep
    // the upsert path free of deeper circular call stacks during bind.
    const inserted: WorkspaceInfo = {
      wsId,
      name: patch.name ?? "未命名对话",
      location: patch.location ?? "cloud",
      rootId: patch.rootId ?? null,
      subpath: patch.subpath ?? "",
      hasFiles: patch.hasFiles ?? false,
    };
    return [inserted, ...list];
  });
}

/** Drop a conversation scratch from the rail (e.g. after unbind with no files). */
export function removeConversationScratch(conversationId: string): void {
  const wsId = `conv:${conversationId}`;
  writeWorkspaces((list) => list.filter((w) => w.wsId !== wsId));
}
