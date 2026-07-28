import {
  getConversations,
  patchConversationCache,
} from "@/hooks/useConversations";
import { patchConversationScratch } from "@/hooks/useWorkspaces";
import { hasLocalFiles } from "@/lib/capabilities";
import { ApiError } from "@/services/api";
import { bareConversationScratchSubpath } from "@/services/bareScratchPath";
import {
  type WorkspaceBinding,
  bindLocalWorkspace,
} from "@/services/workspaceBinding";
import { useBackgroundTasksStore } from "@/stores/backgroundTasks";
import type { FsRoot } from "@shared/ipc-contract";

/** Fired after a successful bind so composer / mode-bar chips can refresh. */
export const WORKSPACE_BINDING_CHANGED = "agentcore:workspace-binding-changed";

/** Answer text so the CEO/worker LLM sees which folder was bound. */
export function formatBindLocalFolderAnswer(
  optionLabel: string,
  folderName: string,
): string {
  return `${optionLabel}（${folderName}）`;
}

export type PickAndBindResult =
  | { ok: true; root: FsRoot; binding: WorkspaceBinding }
  | { ok: false; reason: "cancelled" | "unavailable" }
  | { ok: false; reason: "error"; message: string };

function describeBindError(e: unknown): string {
  if (e instanceof ApiError && e.status === 404) {
    return "对话不存在或无权访问";
  }
  return e instanceof Error ? e.message : "绑定失败，请重试";
}

/**
 * OS folder picker → authorize root → bind conversation **scratch** workspace
 * (``conversations/<id>``) for local execution. Not 「打开项目」—
 * see {@link pickAndOpenLocalProject} for Folder + new conversation.
 * Returns `cancelled` when the user dismisses the picker (caller must not resolve).
 */
export async function pickAndBindLocalFolder(
  conversationId: string,
): Promise<PickAndBindResult> {
  if (!hasLocalFiles() || !window.fsApi) {
    return { ok: false, reason: "unavailable" };
  }
  try {
    const root = await window.fsApi.addRoot();
    if (!root) return { ok: false, reason: "cancelled" };
    const binding = await bindLocalWorkspace(conversationId, root.id);
    if (binding.rootId) {
      const title =
        getConversations().find((c) => c.id === conversationId)?.title ??
        undefined;
      patchConversationScratch(conversationId, {
        ...(title ? { name: title } : {}),
        rootId: binding.rootId,
        location: "local",
        hasFiles: true,
        subpath: bareConversationScratchSubpath(conversationId),
      });
      patchConversationCache(conversationId, {
        localRootId: binding.rootId,
      });
    }
    useBackgroundTasksStore.setState((s) => ({
      modeByConversation: {
        ...s.modeByConversation,
        [conversationId]: binding.mode,
      },
      rootIdByConversation: {
        ...s.rootIdByConversation,
        [conversationId]: binding.rootId,
      },
    }));
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent(WORKSPACE_BINDING_CHANGED, {
          detail: { conversationId },
        }),
      );
    }
    return { ok: true, root, binding };
  } catch (e) {
    return { ok: false, reason: "error", message: describeBindError(e) };
  }
}

/** Draft-only: authorize a folder without binding (no conversation yet). */
export async function pickLocalFolderRoot(): Promise<
  | { ok: true; root: FsRoot }
  | { ok: false; reason: "cancelled" | "unavailable" }
> {
  if (!hasLocalFiles() || !window.fsApi) {
    return { ok: false, reason: "unavailable" };
  }
  const root = await window.fsApi.addRoot();
  if (!root) return { ok: false, reason: "cancelled" };
  return { ok: true, root };
}
