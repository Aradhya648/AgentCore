import type { FolderMeta } from "@/services/folders";
import type { Conversation } from "@/stores/conversation";

/** Bare chat: `localContainerRootId` set → local scratch. Project chats inherit folder.mode. */
export function isConversationLocal(
  conv: Pick<Conversation, "localContainerRootId" | "folderId">,
  folder?: Pick<FolderMeta, "mode"> | null,
): boolean {
  if (conv.folderId && folder) return folder.mode === "local";
  return conv.localContainerRootId != null;
}

/**
 * Folder group's workspace mode for the sidebar header — reads project `mode`
 * (project = workspace). No majority vote over member conversations.
 */
export function deriveGroupWorkspaceIsLocal(
  folder: Pick<FolderMeta, "mode">,
): boolean {
  return folder.mode === "local";
}

/**
 * Whether a conversation row should show the cloud icon.
 * Bare rows: cloud only. Group rows: cloud exceptions when the group default
 * is local (desktop noise reduction — never show HardDrive on rows).
 */
export function shouldShowConversationCloudIcon(
  conv: Pick<Conversation, "localContainerRootId" | "folderId">,
  groupIsLocal?: boolean,
  folder?: Pick<FolderMeta, "mode"> | null,
): boolean {
  const convIsLocal = isConversationLocal(conv, folder);
  if (groupIsLocal === undefined) return !convIsLocal;
  if (convIsLocal === groupIsLocal) return false;
  return !convIsLocal;
}
