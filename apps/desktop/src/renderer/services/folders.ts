import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** Sidebar / picker project (= workspace). Mode is set at create and immutable. */
export interface FolderMeta {
  id: string;
  name: string;
  mode: "local" | "cloud";
  localRootId: string | null;
  localSubpath: string | null;
}

/** Server folder payload (`/folders`), generated from OpenAPI. */
type BackendFolder = Schemas["FolderSummary"];

export function toFolder(f: BackendFolder): FolderMeta {
  return {
    id: f.id,
    name: f.name,
    mode: f.mode,
    localRootId: f.local_root_id ?? null,
    localSubpath: f.local_subpath ?? null,
  };
}

export async function listFolders(): Promise<FolderMeta[]> {
  const res = await api.get<BackendFolder[]>("/v1/folders");
  return res.map(toFolder);
}

export interface CreateFolderInput {
  name: string;
  mode: "local" | "cloud";
  localRootId?: string | null;
  localSubpath?: string | null;
}

export interface CreateFolderResult {
  folder: FolderMeta;
  /** False when the server reused an existing local binding (HTTP 200). */
  created: boolean;
}

/** Create a project (= workspace). `mode` is required and immutable after create. */
export async function createFolder(
  input: CreateFolderInput,
): Promise<CreateFolderResult> {
  const body: Schemas["CreateFolderRequest"] = {
    name: input.name,
    mode: input.mode,
    local_root_id: input.mode === "local" ? (input.localRootId ?? null) : null,
    local_subpath: input.mode === "local" ? (input.localSubpath ?? null) : null,
  };
  const { data, status } = await api.postWithStatus<BackendFolder>(
    "/v1/folders",
    body,
  );
  return { folder: toFolder(data), created: status === 201 };
}

/** Rename a folder. Mode / local bind are immutable after create. */
export async function updateFolder(
  id: string,
  patch: { name?: string },
): Promise<FolderMeta> {
  const body: Record<string, unknown> = {};
  if (patch.name !== undefined) body.name = patch.name;
  const res = await api.patch<BackendFolder>(`/v1/folders/${id}`, body);
  return toFolder(res);
}

export async function deleteFolder(id: string): Promise<void> {
  await api.delete(`/v1/folders/${id}`);
}

/** Hard-delete a folder and every member conversation + cloud workspace (彻底删除项目). */
export async function permanentDeleteFolder(id: string): Promise<void> {
  await api.delete(`/v1/folders/${id}/permanent`);
}

/** Safe relative segment under the default container (`~/Documents/AgentCore/<name>`). */
export function sanitizeProjectSubpath(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[\\/:*?"<>|]/g, "_")
    .replace(/\s+/g, " ")
    .slice(0, 80)
    .trim();
  return cleaned || "project";
}

/** Local binding key; empty / null subpath collapse to the same slot. */
export function localFolderBindingKey(
  localRootId: string,
  localSubpath: string | null | undefined,
): string {
  return `${localRootId}\0${localSubpath || ""}`;
}

/**
 * Find a live local project by FS binding (cache-side reuse before create).
 * First match wins — when the list is created_at asc, that is the oldest row.
 */
export function findLocalFolderByBinding(
  folders: FolderMeta[],
  localRootId: string,
  localSubpath: string | null | undefined,
): FolderMeta | undefined {
  const key = localFolderBindingKey(localRootId, localSubpath);
  return folders.find(
    (f) =>
      f.mode === "local" &&
      !!f.localRootId &&
      localFolderBindingKey(f.localRootId, f.localSubpath) === key,
  );
}

/**
 * Dedupe local projects by binding for picker / list UIs; keep first occurrence
 * (grouped cache is created_at asc → oldest). Cloud rows are never collapsed.
 */
export function dedupeFoldersByLocalBinding(
  folders: FolderMeta[],
): FolderMeta[] {
  const seen = new Set<string>();
  const out: FolderMeta[] = [];
  for (const f of folders) {
    if (f.mode === "local" && f.localRootId) {
      const key = localFolderBindingKey(f.localRootId, f.localSubpath);
      if (seen.has(key)) continue;
      seen.add(key);
    }
    out.push(f);
  }
  return out;
}
