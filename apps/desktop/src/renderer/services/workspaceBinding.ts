import { api } from "@/services/api";
import type { components } from "@/types/api.generated";
import type { FsRoot } from "@shared/ipc-contract";

type Schemas = components["schemas"];

/**
 * Local-mode workspace binding (双模式工作区 §七) — the desktop half of "模式跟着
 * 文件在哪自动走". A conversation is *cloud* by default and flips to *local* once
 * its governing scope (its folder when filed, else the conversation itself) is
 * bound to a desktop FS root. These wrap the conversation-scoped binding endpoints
 * the server exposes; binding through a foldered conversation writes the folder,
 * so every sibling flips too (the server decides the scope and reports it back).
 */

/** Workspace mode (generated from backend `WorkspaceBindingResponse.mode`). */
export type WorkspaceMode = Schemas["WorkspaceBindingResponse"]["mode"];
/** Binding scope (generated from backend `WorkspaceBindingResponse.scope`). */
type BindingScope = Schemas["WorkspaceBindingResponse"]["scope"];

export interface WorkspaceBinding {
  mode: WorkspaceMode;
  /** Where the binding lives — `folder` means the conversation inherits the project. */
  scope: BindingScope;
  /** The bound desktop root id when local; null when cloud. */
  rootId: string | null;
  /** How the effective bind was chosen (explicit project/bind vs container default). */
  source: "explicit" | "container" | null;
}

/** Server binding payload (`/workspace/binding`), generated from OpenAPI. */
type BackendBinding = Schemas["WorkspaceBindingResponse"];

function toBinding(b: BackendBinding): WorkspaceBinding {
  return {
    mode: b.mode,
    scope: b.scope,
    rootId: b.root_id ?? null,
    source: b.source ?? null,
  };
}

/** Resolve a conversation's current workspace mode (cloud vs local). */
export async function getWorkspaceBinding(
  conversationId: string,
): Promise<WorkspaceBinding> {
  return toBinding(
    await api.get<BackendBinding>(
      `/v1/conversations/${conversationId}/workspace/binding`,
    ),
  );
}

/** Bind the conversation's workspace to a desktop root (switch to local mode). */
export async function bindLocalWorkspace(
  conversationId: string,
  rootId: string,
): Promise<WorkspaceBinding> {
  return toBinding(
    await api.put<BackendBinding>(
      `/v1/conversations/${conversationId}/workspace/binding`,
      { root_id: rootId },
    ),
  );
}

/** Unbind the conversation's workspace (fall back to cloud mode). */
export async function unbindWorkspace(
  conversationId: string,
): Promise<WorkspaceBinding> {
  return toBinding(
    await api.delete<BackendBinding>(
      `/v1/conversations/${conversationId}/workspace/binding`,
    ),
  );
}

/**
 * True when a binding points at a desktop root this device no longer has — the
 * "路径不存在" degradation (§八): the root was removed, or it was bound on another
 * device (local projects don't follow you across machines). The UI then offers a
 * reconnect (re-pick the folder) or a switch back to cloud, never failing silently.
 */
export function isBoundRootMissing(
  binding: WorkspaceBinding | null,
  roots: readonly FsRoot[],
): boolean {
  if (!binding || binding.mode !== "local" || !binding.rootId) return false;
  return !roots.some((r) => r.id === binding.rootId);
}
