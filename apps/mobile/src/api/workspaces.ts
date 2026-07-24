// First-class workspace REST for the mobile 文件 tab (跨工作区文件总览).
//
// Reads workspace endpoints by ws_id (`folder:<id>`). Cloud-only on mobile (local
// workspaces are desktop-only). REST wire types track OpenAPI; `WorkspaceSummary`
// is the mobile camelCase view (mirrors desktop `WorkspaceInfo`).
import { apiFetch } from "@/api/client";
import type { DownloadedFile, WorkspaceFileEntry } from "@/api/workspace";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

type WorkspaceListResponse = Schemas["WorkspaceListResponse"];
type WorkspaceFileListResponse = Schemas["WorkspaceFileListResponse"];

/** One of the user's workspaces (a project/folder), as listed for the 文件 tab. */
export interface WorkspaceSummary {
  wsId: string;
  name: string;
  location: "cloud" | "local";
  hasFiles: boolean;
}

/** Enumerate the user's workspaces (cloud + local). Caller filters to cloud on mobile. */
export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  const res = await apiFetch("/v1/workspaces");
  if (!res.ok) throw new Error(`加载工作区失败 (${res.status})`);
  const data = (await res.json()) as WorkspaceListResponse;
  return data.data.map((w) => ({
    wsId: w.ws_id,
    name: w.name,
    location: w.location,
    hasFiles: w.has_files,
  }));
}

const wsBase = (wsId: string): string =>
  `/v1/workspaces/${encodeURIComponent(wsId)}`;

const encodePath = (path: string): string =>
  path.split("/").map(encodeURIComponent).join("/");

/** A cloud workspace's whole tree as a flat recursive listing. */
export async function listWorkspaceFilesByWs(
  wsId: string,
): Promise<WorkspaceFileEntry[]> {
  const res = await apiFetch(`${wsBase(wsId)}/files?recursive=true`);
  if (!res.ok) throw new Error(`加载文件列表失败 (${res.status})`);
  const data = (await res.json()) as WorkspaceFileListResponse;
  return data.data;
}

/** Fetch one file's raw bytes (Bearer-authenticated). */
export async function downloadWorkspaceFileByWs(
  wsId: string,
  path: string,
): Promise<DownloadedFile> {
  const res = await apiFetch(`${wsBase(wsId)}/files/${encodePath(path)}`);
  if (!res.ok) throw new Error(`下载文件失败 (${res.status})`);
  const blob = await res.blob();
  return {
    blob,
    filename: path.split("/").pop() || "download",
    contentType:
      res.headers.get("Content-Type") ||
      blob.type ||
      "application/octet-stream",
  };
}

/** Upload (create/overwrite) a file at `path` from raw bytes. */
export async function uploadWorkspaceFileByWs(
  wsId: string,
  path: string,
  file: Blob,
): Promise<void> {
  const res = await apiFetch(`${wsBase(wsId)}/files/${encodePath(path)}`, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    let message = `上传失败 (${res.status})`;
    try {
      const body = (await res.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }
}
