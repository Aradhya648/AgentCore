// Workspace file REST for the mobile client (前端技术与架构 §七 · 云端文件浏览).
//
// The conversation's cloud workspace over the same endpoints the desktop uses.
// The mobile browser fetches the whole tree once (recursive) and navigates in memory.
// Download needs the Bearer header via apiFetch. REST DTOs track OpenAPI.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type WorkspaceFileEntry = Schemas["WorkspaceFileEntry"];
export type UploadedFile = Schemas["UploadFileResponse"];

type WorkspaceFileListResponse = Schemas["WorkspaceFileListResponse"];

/** A folder/file node in the navigable tree (derived from the flat listing). */
export interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
}

/** A downloaded file's bytes plus the name to save it as and its resolved type. */
export interface DownloadedFile {
  blob: Blob;
  filename: string;
  contentType: string;
}

/** The conversation's whole workspace tree as a flat recursive listing. */
export async function listWorkspaceFiles(
  conversationId: string,
): Promise<WorkspaceFileEntry[]> {
  const res = await apiFetch(
    `/v1/conversations/${conversationId}/workspace/files?recursive=true`,
  );
  if (!res.ok) throw new Error(`加载文件列表失败 (${res.status})`);
  const data = (await res.json()) as WorkspaceFileListResponse;
  return data.data;
}

/** Upload (create/overwrite) a file at `path` from raw bytes. */
export async function uploadWorkspaceFile(
  conversationId: string,
  path: string,
  file: Blob,
): Promise<UploadedFile> {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const res = await apiFetch(
    `/v1/conversations/${conversationId}/workspace/files/${encoded}`,
    {
      method: "PUT",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    },
  );
  if (!res.ok) {
    let message = `上传失败 (${res.status})`;
    try {
      const body = (await res.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      /* non-JSON error body → keep the status fallback */
    }
    throw new Error(message);
  }
  return (await res.json()) as UploadedFile;
}

/** Fetch one file's raw bytes (Bearer-authenticated). */
export async function downloadWorkspaceFile(
  conversationId: string,
  path: string,
): Promise<DownloadedFile> {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const res = await apiFetch(
    `/v1/conversations/${conversationId}/workspace/files/${encoded}`,
  );
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

/** Group a flat recursive listing into `dir → sorted children`. */
export function buildTree(
  entries: WorkspaceFileEntry[],
): Map<string, FileNode[]> {
  const byDir = new Map<string, Map<string, FileNode>>();
  const bucket = (dir: string): Map<string, FileNode> => {
    let m = byDir.get(dir);
    if (!m) {
      m = new Map();
      byDir.set(dir, m);
    }
    return m;
  };
  for (const entry of entries) {
    const segs = entry.path.split("/").filter(Boolean);
    let parent = "";
    segs.forEach((name, i) => {
      const full = parent ? `${parent}/${name}` : name;
      const isDir = i < segs.length - 1 ? true : entry.is_dir;
      const here = bucket(parent);
      const prev = here.get(name);
      if (!prev) here.set(name, { name, path: full, isDir });
      else if (isDir) prev.isDir = true;
      parent = full;
    });
  }
  const out = new Map<string, FileNode[]>();
  for (const [dir, m] of byDir) {
    out.set(
      dir,
      [...m.values()].sort((a, b) =>
        a.isDir !== b.isDir ? (a.isDir ? -1 : 1) : a.name.localeCompare(b.name),
      ),
    );
  }
  return out;
}
