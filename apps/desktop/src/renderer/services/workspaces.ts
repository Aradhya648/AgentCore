import { BASE_URL, api } from "@/services/api";
import {
  type FilePreview,
  type WorkspaceEditDoc,
  type WorkspaceFile,
  type WorkspaceWriteOutcome,
  authedFetch,
  decodePreviewResponse,
  encodePath,
  saveBlob,
} from "@/services/workspaceHttp";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/**
 * The first-class workspace REST client, addressed by **workspace id** (文件中枢
 * 统一 Step 1/2): `ws_id = "conv:<conversationId>"` (primary). This backs the file hub,
 * which browses *conversation scratch spaces* — distinct from `services/workspace` (the
 * per-conversation alias kept for the chat panel). Both hit the same server service
 * layer; only the addressing differs. File/CRUD here are valid for **cloud**
 * workspaces — local ones are reached over desktop IPC (the server returns 409),
 * so the hub picks `LocalRootSource` for those (§五).
 */

export interface WorkspaceInfo {
  wsId: string;
  name: string;
  location: "cloud" | "local";
  /** The bound desktop root id when local; null when cloud. */
  rootId: string | null;
  /** Sub-path within the bound local root (工作区对称化 D1a); "" = the root itself
   * (an explicitly-added local project) or cloud. A non-empty segment marks a
   * per-conversation workspace lazily promoted under a shared container root —
   * the hub scopes its browse ops to this subtree. */
  subpath: string;
  hasFiles: boolean;
}

/** Enumerate the user's workspaces for the hub rail. */
export async function listWorkspaces(): Promise<WorkspaceInfo[]> {
  const res = await api.get<Schemas["WorkspaceListResponse"]>("/v1/workspaces");
  return res.data.map((w) => ({
    wsId: w.ws_id,
    name: w.name,
    location: w.location,
    rootId: w.root_id ?? null,
    subpath: w.subpath ?? "",
    hasFiles: w.has_files,
  }));
}

const wsPath = (wsId: string): string =>
  `/v1/workspaces/${encodeURIComponent(wsId)}`;
const wsUrl = (wsId: string): string => `${BASE_URL}${wsPath(wsId)}`;

/** List a workspace's entries (recursive POSIX paths). */
export async function wsListFiles(
  wsId: string,
  recursive = true,
): Promise<WorkspaceFile[]> {
  const res = await api.get<Schemas["WorkspaceFileListResponse"]>(
    `${wsPath(wsId)}/files?recursive=${recursive}`,
  );
  return res.data.map((e) => ({ path: e.path, isDir: e.is_dir }));
}

/**
 * Flat file-path list for @ mentions (文件中枢统一 F4). Files only, ignore-pruned,
 * capped server-side — the cloud counterpart to `fsApi.listFiles` over a local
 * root, so @ indexes cloud and local workspaces the same way. Cloud-only (the
 * server refuses local workspaces with 409). `truncated` is dropped here: the @
 * index is best-effort, matching how local indexing ignores its own cap.
 */
export async function wsListFileIndex(wsId: string): Promise<string[]> {
  const res = await api.get<Schemas["WorkspaceFileIndexResponse"]>(
    `${wsPath(wsId)}/file-index`,
  );
  return res.data;
}

/** Upload (create/overwrite) a workspace file from raw bytes. */
export async function wsUploadFile(
  wsId: string,
  path: string,
  body: Blob,
): Promise<void> {
  await authedFetch(`${wsUrl(wsId)}/files/${encodePath(path)}`, {
    method: "PUT",
    body,
  });
}

/** Export a workspace Markdown file to a sibling ``.docx`` (server converter). */
export async function wsExportMdToDocx(
  wsId: string,
  path: string,
): Promise<{ path: string; warnings: string[] }> {
  const res = await api.post<{
    path: string;
    source_path: string;
    size_bytes: number;
    warnings: string[];
  }>(`${wsPath(wsId)}/export-docx`, { path });
  return { path: res.path, warnings: res.warnings ?? [] };
}

/** Stateless Markdown → Word (local desktop path; images as base64). */
export async function convertMdToDocx(input: {
  markdown: string;
  images: Record<string, string | null>;
  sourceName: string;
}): Promise<{ docxBase64: string; warnings: string[]; suggestedFilename: string }> {
  const res = await api.post<{
    docx_base64: string;
    warnings: string[];
    suggested_filename: string;
  }>("/v1/workspaces/convert/md-to-docx", {
    markdown: input.markdown,
    images: input.images,
    source_name: input.sourceName,
  });
  return {
    docxBase64: res.docx_base64,
    warnings: res.warnings ?? [],
    suggestedFilename: res.suggested_filename,
  };
}

/** Delete a workspace file or directory (directories go recursively). */
export async function wsDeleteFile(wsId: string, path: string): Promise<void> {
  await api.delete(`${wsPath(wsId)}/files/${encodePath(path)}`);
}

/** Move/rename a workspace file or directory (`AlreadyExists` → 422). */
export async function wsMoveFile(
  wsId: string,
  src: string,
  dst: string,
): Promise<void> {
  await api.post(`${wsPath(wsId)}/move`, { src, dst });
}

/** Create a workspace directory (parents created; `AlreadyExists` → 422). */
export async function wsCreateDir(wsId: string, path: string): Promise<void> {
  await api.post(`${wsPath(wsId)}/dirs`, { path });
}

/** Download a workspace file and save it via the browser. */
export async function wsDownloadFile(
  wsId: string,
  path: string,
  filename: string,
): Promise<void> {
  const res = await authedFetch(`${wsUrl(wsId)}/files/${encodePath(path)}`);
  await saveBlob(await res.blob(), filename);
}

/** Read a workspace file for read-only in-panel preview. */
export async function wsReadFile(
  wsId: string,
  path: string,
): Promise<FilePreview> {
  const res = await authedFetch(`${wsUrl(wsId)}/files/${encodePath(path)}`);
  return decodePreviewResponse(res);
}

/** Read a cloud-workspace file for **editing** (full text + mtime CAS baseline). */
export async function wsReadFileForEdit(
  wsId: string,
  path: string,
): Promise<WorkspaceEditDoc> {
  const res = await api.get<Schemas["WorkspaceEditDoc"]>(
    `${wsPath(wsId)}/edit/${encodePath(path)}`,
  );
  return { text: res.text, mtimeMs: res.mtime_ms, eol: res.eol };
}

/** Conditionally write editor text back (mtime CAS); conflict carries disk mtime. */
export async function wsWriteFileText(
  wsId: string,
  path: string,
  input: { content: string; eol: "lf" | "crlf"; baselineMtimeMs: number },
): Promise<WorkspaceWriteOutcome> {
  const res = await api.put<Schemas["WorkspaceWriteResult"]>(
    `${wsPath(wsId)}/edit/${encodePath(path)}`,
    {
      content: input.content,
      eol: input.eol,
      baseline_mtime_ms: input.baselineMtimeMs,
    } satisfies Schemas["WorkspaceWriteRequest"],
  );
  return { ok: res.ok, mtimeMs: res.mtime_ms, conflict: res.conflict };
}
