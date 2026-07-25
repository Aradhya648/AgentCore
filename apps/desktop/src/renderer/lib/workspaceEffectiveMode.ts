import type { WorkspaceBinding } from "@/services/workspaceBinding";
import { isBoundRootMissing } from "@/services/workspaceBinding";
import type { FsRoot } from "@shared/ipc-contract";

/**
 * Effective workspace location for UI chips / mode bars.
 *
 * Turn routing uses `local_root_id` **or** `local_container_root_id` (sidecar /
 * cloud-turn binding). Project conversations inherit the folder bind
 * (`scope=folder`); bare chats use conversation bind or default container.
 */
export interface EffectiveWorkspace {
  /** True when turns route to a local root (bound folder or default container). */
  isLocal: boolean;
  /** Root id used for display / missing-root checks (bound root preferred). */
  rootId: string | null;
  /** Human folder name when resolvable from the desktop root list. */
  rootName: string | null;
  /** Explicit bind whose root is gone on this device (§八). */
  rootMissing: boolean;
  /** True when locality comes from default container, not an explicit bind. */
  viaContainer: boolean;
  /** Project name when the conversation inherits a folder workspace. */
  projectName: string | null;
  /** Binding lives on the project (vs bare conversation scratch). */
  viaProject: boolean;
}

export function resolveEffectiveWorkspace(opts: {
  binding: WorkspaceBinding | null;
  localContainerRootId: string | null | undefined;
  roots: readonly FsRoot[];
  projectName?: string | null;
}): EffectiveWorkspace {
  const { binding, localContainerRootId, roots, projectName = null } = opts;
  const viaProject = binding?.scope === "folder";
  const boundRootId =
    binding?.mode === "local" && binding.rootId ? binding.rootId : null;

  if (boundRootId) {
    const rootName = roots.find((r) => r.id === boundRootId)?.name ?? null;
    return {
      isLocal: true,
      rootId: boundRootId,
      rootName,
      rootMissing: isBoundRootMissing(binding, roots),
      viaContainer: binding?.source === "container",
      projectName: viaProject ? projectName : null,
      viaProject,
    };
  }

  if (localContainerRootId) {
    const rootName =
      roots.find((r) => r.id === localContainerRootId)?.name ?? null;
    return {
      isLocal: true,
      rootId: localContainerRootId,
      rootName,
      rootMissing: !roots.some((r) => r.id === localContainerRootId),
      viaContainer: true,
      projectName: null,
      viaProject: false,
    };
  }

  return {
    isLocal: false,
    rootId: null,
    rootName: null,
    rootMissing: false,
    viaContainer: false,
    projectName: viaProject ? projectName : null,
    viaProject,
  };
}

/**
 * Chip / mode-bar label:
 * - project: 「项目名 · 本地|云端」
 * - bare local: 「本机草稿」
 * - bare cloud: 「快速对话」（与 draft chip 对齐）
 */
export function formatWorkspaceChipLabel(ws: EffectiveWorkspace): string {
  if (ws.viaProject && ws.projectName) {
    return `${ws.projectName} · ${ws.isLocal ? "本地" : "云端"}`;
  }
  if (ws.isLocal) return "本机草稿";
  return "快速对话";
}
