import { ensureDefaultContainerRoot } from "@/services/defaultWorkspace";
import { useConversationStore } from "@/stores/conversation";
import { useFoldersStore } from "@/stores/folders";
import type { NavigateFunction } from "react-router-dom";

/**
 * 开启一个全新的草稿对话并跳到 `/`。草稿只活在 store 里（不落库），首条消息发送时
 * 才由 MessageInput 真正在后端创建会话。
 *
 * - 不传 folderId：默认云端裸聊草稿（桌面裸聊默认切云 §八.7）
 * - 传 folderId：项目草稿（出生定终身继承项目工作区）
 * - `opts.cloud`：显式云端草稿（与默认同）
 * - `opts.local`：显式本机草稿（容器根 + sidecar）
 */
export function startNewConversation(
  navigate: NavigateFunction,
  folderId?: string | null,
  opts?: { cloud?: boolean; local?: boolean },
): void {
  const foldersStore = useFoldersStore.getState();
  if (opts?.local) {
    foldersStore.setDraftWorkspaceIntent({ kind: "quick_local" });
    void ensureDefaultContainerRoot();
  } else if (opts?.cloud) {
    foldersStore.setDraftWorkspaceIntent({ kind: "quick_cloud" });
  } else if (folderId) {
    foldersStore.setDraftWorkspaceIntent({
      kind: "project",
      folderId,
    });
  } else {
    foldersStore.resetDraftWorkspaceIntent();
  }
  useConversationStore.getState().switchConversation(null);
  navigate("/");
}
