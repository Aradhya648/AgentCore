import { hasLocalFiles } from "@/lib/capabilities";
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
 * Conversation-scoped workspace REST client — the per-conversation alias used by
 * the chat panel: every op hits `/v1/conversations/{id}/workspace/...`. The file
 * hub instead addresses workspaces by id via `services/workspaces`; both share the
 * neutral primitives in `services/workspaceHttp` and hit the same server service
 * layer, only the addressing differs. Snapshots live here because they are a
 * conversation-scoped concern with no ws-id counterpart.
 */

const filesBase = (conversationId: string): string =>
  `${BASE_URL}/v1/conversations/${conversationId}/workspace/files`;

// --- Files (bring files in / take results out: 文件进出) ---

/** List the conversation's workspace entries (recursive POSIX paths). */
export async function listWorkspaceFiles(
  conversationId: string,
  recursive = true,
): Promise<WorkspaceFile[]> {
  const res = await api.get<Schemas["WorkspaceFileListResponse"]>(
    `/v1/conversations/${conversationId}/workspace/files?recursive=${recursive}`,
  );
  return res.data.map((e) => ({ path: e.path, isDir: e.is_dir }));
}

/** Upload (create/overwrite) a workspace file from raw bytes. */
export async function uploadWorkspaceFile(
  conversationId: string,
  path: string,
  body: Blob,
): Promise<void> {
  await authedFetch(`${filesBase(conversationId)}/${encodePath(path)}`, {
    method: "PUT",
    body,
  });
}

/** Export a conversation-workspace Markdown file to a sibling ``.docx``. */
export async function exportWorkspaceMdToDocx(
  conversationId: string,
  path: string,
): Promise<{ path: string; warnings: string[] }> {
  const res = await api.post<{
    path: string;
    source_path: string;
    size_bytes: number;
    warnings: string[];
  }>(`/v1/conversations/${conversationId}/workspace/export-docx`, { path });
  return { path: res.path, warnings: res.warnings ?? [] };
}

/** Delete a workspace file or directory (directories go recursively). */
export async function deleteWorkspaceFile(
  conversationId: string,
  path: string,
): Promise<void> {
  await api.delete(
    `/v1/conversations/${conversationId}/workspace/files/${encodePath(path)}`,
  );
}

/** Move/rename a workspace file or directory (`AlreadyExists` → 422). */
export async function moveWorkspaceFile(
  conversationId: string,
  src: string,
  dst: string,
): Promise<void> {
  await api.post(`/v1/conversations/${conversationId}/workspace/move`, {
    src,
    dst,
  });
}

/** Create a workspace directory (parents created; `AlreadyExists` → 422). */
export async function createWorkspaceDir(
  conversationId: string,
  path: string,
): Promise<void> {
  await api.post(`/v1/conversations/${conversationId}/workspace/dirs`, {
    path,
  });
}

/**
 * Download a file from a conversation's workspace and save it via the browser.
 *
 * The file API is JSON-less (raw bytes), so this fetches directly (reusing the
 * shared cookie auth + refresh-once) and triggers a save through an object-URL
 * anchor. Backs both the resident-attachment chip (附件驻留) and the workspace
 * panel's per-file download.
 */
export async function downloadWorkspaceFile(
  conversationId: string,
  workspacePath: string,
  filename: string,
): Promise<void> {
  const res = await authedFetch(
    `${filesBase(conversationId)}/${encodePath(workspacePath)}`,
  );
  await saveBlob(await res.blob(), filename);
}

/**
 * Fetch a conversation-workspace file as a Blob (for inline rendering via an object
 * URL) — the raw-bytes twin of {@link downloadWorkspaceFile}, reusing the shared
 * cookie auth + refresh-once. Backs the 团队浏览器活动卡 key-frame lazy load (mirrors
 * the IM `fetchChatAttachmentBlob` blob + objectURL pattern, only the addressing —
 * conversation workspace vs chat space — differs).
 */
export async function fetchWorkspaceFileBlob(
  conversationId: string,
  workspacePath: string,
): Promise<Blob> {
  const res = await authedFetch(
    `${filesBase(conversationId)}/${encodePath(workspacePath)}`,
  );
  return res.blob();
}

/** Read a conversation-workspace file for read-only in-panel preview. */
export async function readWorkspaceFile(
  conversationId: string,
  path: string,
): Promise<FilePreview> {
  const res = await authedFetch(
    `${filesBase(conversationId)}/${encodePath(path)}`,
  );
  return decodePreviewResponse(res);
}

// --- Edit (源无关编辑契约的云端实现: full text + mtime CAS) ---

/**
 * Read a conversation-workspace file for **editing** — full text (never truncated,
 * unlike preview) + the mtime baseline a later save does its CAS against. The
 * editable counterpart of {@link readWorkspaceFile}.
 */
export async function readWorkspaceFileForEdit(
  conversationId: string,
  path: string,
): Promise<WorkspaceEditDoc> {
  const res = await api.get<Schemas["WorkspaceEditDoc"]>(
    `/v1/conversations/${conversationId}/workspace/edit/${encodePath(path)}`,
  );
  return { text: res.text, mtimeMs: res.mtime_ms, eol: res.eol };
}

/**
 * Conditionally write editor text back (mtime CAS). A `conflict` (disk changed
 * since `baselineMtimeMs`, e.g. an Agent turn wrote it) returns `ok:false` with the
 * disk mtime instead of clobbering — never a blind overwrite.
 */
export async function writeWorkspaceFileText(
  conversationId: string,
  path: string,
  input: { content: string; eol: "lf" | "crlf"; baselineMtimeMs: number },
): Promise<WorkspaceWriteOutcome> {
  const res = await api.put<Schemas["WorkspaceWriteResult"]>(
    `/v1/conversations/${conversationId}/workspace/edit/${encodePath(path)}`,
    {
      content: input.content,
      eol: input.eol,
      baseline_mtime_ms: input.baselineMtimeMs,
    } satisfies Schemas["WorkspaceWriteRequest"],
  );
  return { ok: res.ok, mtimeMs: res.mtime_ms, conflict: res.conflict };
}

// --- Snapshots (axis-3 persistence: backup / kept versions / download) ---

export interface WorkspaceSnapshot {
  snapshotId: string;
  /** A user-pinned name (手动留版本), or null for an automatic post-turn backup. */
  label: string | null;
  createdAt: string;
  sizeBytes: number;
}

/** Server snapshot payload (`/snapshots`), generated from OpenAPI. */
type BackendSnapshot = Schemas["SnapshotSummary"];

const toSnapshot = (s: BackendSnapshot): WorkspaceSnapshot => ({
  snapshotId: s.snapshot_id,
  label: s.label,
  createdAt: s.created_at,
  sizeBytes: s.size_bytes,
});

/** List the conversation's workspace snapshots (newest first). */
export async function listSnapshots(
  conversationId: string,
): Promise<WorkspaceSnapshot[]> {
  const res = await api.get<Schemas["SnapshotListResponse"]>(
    `/v1/conversations/${conversationId}/snapshots`,
  );
  return res.data.map(toSnapshot);
}

/** Take a manual snapshot; a non-empty `label` keeps it as a named version. */
export async function createSnapshot(
  conversationId: string,
  label?: string,
): Promise<WorkspaceSnapshot> {
  const res = await api.post<BackendSnapshot>(
    `/v1/conversations/${conversationId}/snapshots`,
    { label: label?.trim() || null },
  );
  return toSnapshot(res);
}

/** Restore the workspace to a snapshot (overwrites current files). */
export async function restoreSnapshot(
  conversationId: string,
  snapshotId: string,
): Promise<void> {
  await api.post(
    `/v1/conversations/${conversationId}/snapshots/${snapshotId}/restore`,
  );
}

/** Download a snapshot's zip archive and save it via the browser. */
export async function downloadSnapshot(
  conversationId: string,
  snapshotId: string,
): Promise<void> {
  const res = await authedFetch(
    `${BASE_URL}/v1/conversations/${conversationId}/snapshots/${snapshotId}/download`,
  );
  await saveBlob(await res.blob(), `workspace-${snapshotId}.zip`);
}

/** Snapshot current cloud workspace files and download as a zip (产物导出 · web / 兜底). */
export async function exportWorkspaceZip(
  conversationId: string,
): Promise<void> {
  const snap = await createSnapshot(conversationId, "导出");
  await downloadSnapshot(conversationId, snap.snapshotId);
}

/** blob → base64（分块，避免大文件撑爆调用栈）。 */
async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export type ExportWorkspaceToLocalResult =
  | { ok: true; destName: string; fileCount: number }
  | { ok: false; reason: "cancelled" }
  | { ok: false; reason: "unavailable" }
  | { ok: false; reason: "error"; message: string };

/**
 * 云 scratch → 本地单向 checkout（§八.7）：快照 → 用户选目录 → 解压落地。
 * 预览仍走既有云工作区浏览面；本函数只负责落地。非桌面 → unavailable。
 */
export async function exportWorkspaceToLocal(
  conversationId: string,
): Promise<ExportWorkspaceToLocalResult> {
  if (!hasLocalFiles() || !window.fsApi?.checkoutArchive) {
    return { ok: false, reason: "unavailable" };
  }
  const snap = await createSnapshot(conversationId, "导出到本地");
  const res = await authedFetch(
    `${BASE_URL}/v1/conversations/${conversationId}/snapshots/${snap.snapshotId}/download`,
  );
  const archiveBase64 = await blobToBase64(await res.blob());
  return window.fsApi.checkoutArchive(archiveBase64);
}

/**
 * 「在浏览器打开」云端工作区里的某个页面：快照 → 下载 zip → 主进程解压临时目录 →
 * 系统默认浏览器打开该文件。真实浏览器 = 完整 JS + 多文件相对资源（面板内只显示
 * 源码，效果一律出面板看）。桌面专属；失败抛异常（供 UI toast）。
 */
export async function openWorkspaceInBrowser(
  conversationId: string,
  htmlPath: string,
): Promise<void> {
  const preview = window.fsApi?.previewArchive;
  if (!preview) throw new Error("此环境不支持在浏览器打开");
  const snap = await createSnapshot(conversationId, "浏览器预览");
  const res = await authedFetch(
    `${BASE_URL}/v1/conversations/${conversationId}/snapshots/${snap.snapshotId}/download`,
  );
  const archiveBase64 = await blobToBase64(await res.blob());
  const result = await preview(archiveBase64, htmlPath);
  if (!result.ok) throw new Error(result.message);
}

/**
 * 应用内「完整预览」：打开独立子窗口，主进程经 `preview://` 协议以 Bearer 代理
 * 会话工作区字节，完整跑 JS + 多文件相对资源。比「在浏览器打开」更轻——无需快照/打包/解压，
 * 文件按需从后端取。桌面专属（依赖 previewApi）；失败抛异常（供 UI toast）。
 */
export async function openWorkspaceInAppPreview(
  conversationId: string,
  htmlPath: string,
): Promise<void> {
  const open = window.previewApi?.open;
  if (!open) throw new Error("此环境不支持应用内预览");
  const result = await open({ conversationId, path: htmlPath });
  if (!result.ok) throw new Error(result.reason);
}
