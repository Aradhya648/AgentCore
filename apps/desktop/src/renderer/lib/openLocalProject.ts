import { addFolderCache, getFolders } from "@/hooks/useFolders";
import { pickLocalFolderRoot } from "@/lib/bindLocalFolder";
import { hasLocalFiles } from "@/lib/capabilities";
import { startNewConversation } from "@/lib/newConversation";
import { notifyError, notifySuccess } from "@/lib/toast";
import {
  type FolderMeta,
  createFolder,
  findLocalFolderByBinding,
} from "@/services/folders";
import type { FsRoot } from "@shared/ipc-contract";
import type { NavigateFunction } from "react-router-dom";

/** Answer text so the CEO/worker LLM sees which project was opened (new session). */
export function formatOpenLocalProjectAnswer(
  optionLabel: string,
  folderName: string,
): string {
  return `${optionLabel}（${folderName} · 已打开为本地项目，新会话）`;
}

export type PickAndOpenLocalProjectResult =
  | { ok: true; root: FsRoot; folder: FolderMeta; created: boolean }
  | { ok: false; reason: "cancelled" | "unavailable" }
  | { ok: false; reason: "error"; message: string };

/**
 * OS folder picker → create/reuse local Folder (mode=local, empty subpath) →
 * start a **new** conversation under that project.
 *
 * Does **not** rewrite the current session's ``folder_id`` (出生定终身).
 * Distinct from {@link pickAndBindLocalFolder} (bare-chat scratch execution bind).
 */
export async function pickAndOpenLocalProject(
  navigate: NavigateFunction,
): Promise<PickAndOpenLocalProjectResult> {
  if (!hasLocalFiles() || !window.fsApi) {
    return { ok: false, reason: "unavailable" };
  }
  try {
    const picked = await pickLocalFolderRoot();
    if (!picked.ok) return picked;

    const existing = findLocalFolderByBinding(
      getFolders(),
      picked.root.id,
      null,
    );
    let folder: FolderMeta;
    let created: boolean;
    if (existing) {
      folder = existing;
      created = false;
    } else {
      const result = await createFolder({
        name: picked.root.name,
        mode: "local",
        localRootId: picked.root.id,
        localSubpath: null,
      });
      folder = result.folder;
      created = result.created;
      addFolderCache(folder);
    }

    startNewConversation(navigate, folder.id);
    notifySuccess(
      created ? `已创建项目「${folder.name}」` : `已打开项目「${folder.name}」`,
    );
    return { ok: true, root: picked.root, folder, created };
  } catch (e) {
    const message = e instanceof Error ? e.message : "打开本地项目失败，请重试";
    notifyError(e, "打开本地项目失败");
    return { ok: false, reason: "error", message };
  }
}
