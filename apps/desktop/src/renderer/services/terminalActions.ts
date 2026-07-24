import { getConversations } from "@/hooks/useConversations";
import { hasLocalFiles } from "@/lib/capabilities";
import type { FileSource } from "@/lib/fileSource";
import { parentDir } from "@/lib/fileSource";
import { queryClient } from "@/lib/queryClient";
import { workspaceKeys } from "@/lib/queryKeys";
import { notifyActionError, notifyError } from "@/lib/toast";
import {
  createWorkspaceSource,
  resolveConversationLocalFileSource,
  resolveWorkspaceSource,
} from "@/services/sources/workspaceSource";
import type { WorkspaceInfo } from "@/services/workspaces";
import { useConversationStore } from "@/stores/conversation";

/** Imperative resolver — mirrors {@link useConversationFileSource} for palette / shortcuts. */
export async function resolveConversationFileSource(
  conversationId: string,
): Promise<FileSource | null> {
  const fsAvailable = hasLocalFiles();
  const workspaces = queryClient.getQueryData<WorkspaceInfo[]>(
    workspaceKeys.list,
  );
  const ws =
    workspaces?.find((w) => w.wsId === `conv:${conversationId}`) ?? null;
  if (ws) return resolveWorkspaceSource(ws, fsAvailable);

  const conv = getConversations().find((c) => c.id === conversationId);
  if (fsAvailable && conv?.localContainerRootId) {
    return resolveConversationLocalFileSource(conversationId);
  }
  return createWorkspaceSource(conversationId);
}

export async function openFileSourceShell(
  source: FileSource,
  path = ".",
): Promise<void> {
  try {
    if (!source.openShellAtPath) {
      throw new Error("此工作区不支持在终端打开");
    }
    await source.openShellAtPath(path);
  } catch (e) {
    notifyActionError("无法打开终端", e);
  }
}

/** Open a shell at `path` (workspace-relative); files open in their parent directory. */
export async function openShellAtWorkspacePath(
  source: FileSource,
  path: string,
  isDir: boolean,
): Promise<void> {
  const target = isDir || path === "" ? path || "." : parentDir(path);
  await openFileSourceShell(source, target);
}

/** Open the current conversation's local workspace root in the OS terminal. */
export async function openCurrentConversationTerminal(): Promise<void> {
  const id = useConversationStore.getState().currentConversationId;
  if (!id) {
    notifyError("请先打开一个对话");
    return;
  }
  const source = await resolveConversationFileSource(id);
  if (!source?.openShellAtPath) {
    notifyError("当前对话未绑定本地工作区");
    return;
  }
  await openFileSourceShell(source, ".");
}
