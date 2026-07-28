import { useConversations } from "@/hooks/useConversations";
import { useFolders } from "@/hooks/useFolders";
import { useConversationWorkspace } from "@/hooks/useWorkspaces";
import { hasInAppPreview, hasLocalFiles } from "@/lib/capabilities";
import type { FileSource } from "@/lib/fileSource";
import { useReadOnlyOffline } from "@/lib/offlineMode";
import { openWorkspaceHtmlInBrowser } from "@/lib/openWorkspaceHtmlInBrowser";
import { asReadOnlyFileSource } from "@/services/sources/readOnlyFileSource";
import {
  createWorkspaceSource,
  resolveConversationLocalFileSource,
  resolveWorkspaceSource,
} from "@/services/sources/workspaceSource";
import { openWorkspaceInBrowser } from "@/services/workspace";
import { useEffect, useMemo, useState } from "react";

type LocalFallback = "idle" | "pending" | FileSource | null;

/**
 * 给云端会话工作区源挂上 HTML 完整效果的两个 **对话侧栏专属** 出口——应用内「完整预览」
 * （右坞 BrowserPanel + workspace://，不再走已拆除的 openPreview）与「在浏览器打开」
 * （快照解压后系统浏览器）。
 *
 * 二者都**绑定当前 conversationId**：ws-id 寻址的 `createCloudWorkspaceSource`（文件中枢用）刻意
 * 不挂这两个会话作用域出口，避免用错会话寻址；对话侧栏的会话工作区（一旦有文件即被 `/v1/workspaces`
 * 列出、经 `resolveWorkspaceSource` 走 ws-id 源）因此会丢这两个入口——故在这条缝按会话 id 统一补挂
 * （否则「在浏览器打开」会从对话侧栏静默消失）。本地源（`local:` 前缀，自带 IPC 出口）不匹配
 * `workspace:` 前缀 → 不覆盖；web / 无对应能力环境按能力位逐个门控 → 入口不暴露。
 */
function withCloudPreviewEntries(
  source: FileSource | null,
  conversationId: string | null,
): FileSource | null {
  if (!source || !conversationId) return source;
  if (!source.id.startsWith("workspace:")) return source;

  const withEntries: FileSource = { ...source };
  // 完整预览：右坞浏览器壳 + workspace://（L1b 第二 partition）。
  if (hasInAppPreview()) {
    withEntries.openInAppPreview = (path: string) =>
      openWorkspaceHtmlInBrowser(conversationId, path);
  }
  // 在系统浏览器打开 —— 会话工作区快照 → 解压临时目录 → 系统默认浏览器（依赖 previewArchive）。
  if (window.fsApi?.previewArchive) {
    withEntries.openInBrowser = (path: string) =>
      openWorkspaceInBrowser(conversationId, path);
  }
  return withEntries;
}

/**
 * FileSource for a conversation's side-panel file browser.
 * Project local chats inherit folder root+subpath; bare local use container.
 */
export function useConversationFileSource(
  conversationId: string | null,
): FileSource | null {
  const offline = useReadOnlyOffline();
  const ws = useConversationWorkspace(conversationId);
  const fsAvailable = hasLocalFiles();
  const conversations = useConversations();
  const folders = useFolders();
  const conv = conversations.find((c) => c.id === conversationId) ?? null;
  const folder = conv?.folderId
    ? (folders.find((f) => f.id === conv.folderId) ?? null)
    : null;
  const localContainerRootId = conv?.localContainerRootId ?? null;
  const needsLocalFallback =
    (folder?.mode === "local" && !!folder.localRootId) ||
    !!localContainerRootId;

  const [localFallback, setLocalFallback] = useState<LocalFallback>("idle");

  useEffect(() => {
    if (ws || !conversationId) {
      setLocalFallback("idle");
      return;
    }
    if (!fsAvailable || !needsLocalFallback) {
      setLocalFallback(null);
      return;
    }

    let cancelled = false;
    setLocalFallback("pending");
    void resolveConversationLocalFileSource(conversationId).then((source) => {
      if (!cancelled) setLocalFallback(source);
    });
    return () => {
      cancelled = true;
    };
  }, [ws, conversationId, fsAvailable, needsLocalFallback]);

  return useMemo(() => {
    const base = ((): FileSource | null => {
      if (ws) {
        // N4-A: cloud workspaces unavailable offline (hub greys them; side panel too).
        if (offline && ws.location === "cloud") return null;
        const src = resolveWorkspaceSource(ws, fsAvailable);
        if (offline && src && ws.location === "local") {
          return asReadOnlyFileSource(src);
        }
        return src;
      }
      if (!conversationId) return null;

      const awaitingLocal =
        fsAvailable &&
        needsLocalFallback &&
        (localFallback === "pending" || localFallback === "idle");
      if (awaitingLocal) return null;

      if (localFallback && typeof localFallback !== "string") {
        return offline ? asReadOnlyFileSource(localFallback) : localFallback;
      }
      if (offline) return null;
      if (folder && folder.mode === "cloud") {
        return resolveWorkspaceSource(
          {
            wsId: `folder:${folder.id}`,
            name: folder.name,
            location: "cloud",
            rootId: null,
            subpath: "",
            hasFiles: true,
          },
          fsAvailable,
        );
      }
      return createWorkspaceSource(conversationId);
    })();
    // 对话侧栏专属：给云端源挂「完整预览」+「在浏览器打开」出口（均绑定本会话 id）。
    return withCloudPreviewEntries(base, conversationId);
  }, [
    ws,
    conversationId,
    fsAvailable,
    needsLocalFallback,
    localFallback,
    folder,
    offline,
  ]);
}
