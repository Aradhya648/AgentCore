import { getConversations } from "@/hooks/useConversations";
import {
  type FileNode,
  type FilePreviewResult,
  type FileSource,
  baseName,
} from "@/lib/fileSource";
import { resolveConversationLocalTarget } from "@/services/sidecarRouting";
import {
  createWorkspaceDir,
  deleteWorkspaceFile,
  downloadWorkspaceFile,
  listWorkspaceFiles,
  moveWorkspaceFile,
  openWorkspaceInAppPreview,
  openWorkspaceInBrowser,
  readWorkspaceFile,
  readWorkspaceFileForEdit,
  uploadWorkspaceFile,
  writeWorkspaceFileText,
} from "@/services/workspace";
import type {
  WorkspaceEditDoc,
  WorkspaceFile,
  FilePreview as WorkspacePreview,
  WorkspaceWriteOutcome,
} from "@/services/workspaceHttp";
import type { WorkspaceInfo } from "@/services/workspaces";
import {
  wsCreateDir,
  wsDeleteFile,
  wsDownloadFile,
  wsListFileIndex,
  wsListFiles,
  wsMoveFile,
  wsReadFile,
  wsReadFileForEdit,
  wsUploadFile,
  wsWriteFileText,
} from "@/services/workspaces";
import { createLocalRootSource } from "./localRootSource";

/** Map the server preview shape into the unified result (server has no image kind). */
function adaptPreview(p: WorkspacePreview): FilePreviewResult {
  if (p.kind === "text") {
    return { kind: "text", text: p.text, truncated: p.truncated };
  }
  if (p.kind === "too-large") return { kind: "too-large" };
  return { kind: "binary" };
}

/** The cloud workspace caps — shared by the conversation- and ws-id-keyed sources. */
const CLOUD_CAPS = {
  watch: false,
  transfer: true,
  edit: true,
  snapshots: true,
} as const;

/** Viewer / readonly shared-space: browse + download, no mutate / in-panel edit. */
const CLOUD_READONLY_CAPS = {
  watch: false,
  transfer: true,
  edit: false,
  snapshots: false,
} as const;

/**
 * The addressing-agnostic REST surface a cloud {@link FileSource} needs. The two
 * cloud sources differ only in *how they address* their workspace (conversation id
 * vs workspace id), so each binds its own client and shares the source body in
 * {@link makeCloudSource} — the file hub and chat panel can't drift on cloud
 * behaviour. `listFileIndex` is optional: only the ws-id client exposes the @ index.
 */
interface CloudFileClient {
  listFiles(recursive: boolean): Promise<WorkspaceFile[]>;
  read(path: string): Promise<WorkspacePreview>;
  readForEdit(path: string): Promise<WorkspaceEditDoc>;
  writeText(
    path: string,
    input: { content: string; eol: "lf" | "crlf"; baselineMtimeMs: number },
  ): Promise<WorkspaceWriteOutcome>;
  upload(path: string, body: Blob): Promise<void>;
  createDir(path: string): Promise<void>;
  move(src: string, dst: string): Promise<void>;
  delete(path: string): Promise<void>;
  download(path: string, filename: string): Promise<void>;
  listFileIndex?(): Promise<string[]>;
}

/**
 * Build a cloud {@link FileSource} over a {@link CloudFileClient}. The server lists
 * recursively in one call, so `listTree` is the natural primitive and `listDir`
 * derives one level from it. Shared by both cloud factories below so the hub
 * (ws id) and chat panel (conversation id) stay byte-for-byte identical on
 * everything but addressing.
 */
function makeCloudSource(
  key: string,
  label: string,
  client: CloudFileClient,
  caps: typeof CLOUD_CAPS | typeof CLOUD_READONLY_CAPS = CLOUD_CAPS,
): FileSource {
  const listTree = async (): Promise<FileNode[]> => {
    const files = await client.listFiles(true);
    return files.map((f) => ({
      path: f.path,
      name: baseName(f.path),
      isDir: f.isDir,
    }));
  };

  const fileIndex = client.listFileIndex;
  return {
    id: `workspace:${key}`,
    label,
    caps,
    listTree,
    listDir: (dir) => oneLevel(listTree, dir),
    // Feeds the @ index (文件中枢统一 F4) — flat, files-only, server-pruned/capped.
    ...(fileIndex ? { listFileIndex: fileIndex } : {}),
    read: (path) => client.read(path).then(adaptPreview),
    readForEdit: async (path) => {
      const d = await client.readForEdit(path);
      return {
        text: d.text,
        version: { mtimeMs: d.mtimeMs },
        encoding: "utf-8",
        eol: d.eol,
      };
    },
    writeText: async (path, input) => {
      const r = await client.writeText(path, {
        content: input.content,
        eol: input.eol,
        baselineMtimeMs: input.baseline?.mtimeMs ?? 0,
      });
      return r.ok
        ? { ok: true, version: { mtimeMs: r.mtimeMs } }
        : { ok: false, reason: "conflict", version: { mtimeMs: r.mtimeMs } };
    },
    createFile: (path) => client.upload(path, new Blob([])),
    mkdir: (path) => client.createDir(path),
    move: (src, dst) => client.move(src, dst),
    delete: (path) => client.delete(path),
    writeBytes: (path, body) => client.upload(path, body),
    download: (path, filename) => client.download(path, filename),
  };
}

/**
 * A {@link FileSource} over a conversation's server workspace (cloud mode, REST),
 * keyed by conversationId — the chat panel's source (per-conversation alias). The
 * hub addresses the same spaces by workspace id via {@link createCloudWorkspaceSource}.
 */
export function createWorkspaceSource(
  conversationId: string,
  label = "工作区",
): FileSource {
  const source = makeCloudSource(conversationId, label, {
    listFiles: (recursive) => listWorkspaceFiles(conversationId, recursive),
    read: (path) => readWorkspaceFile(conversationId, path),
    readForEdit: (path) => readWorkspaceFileForEdit(conversationId, path),
    writeText: (path, input) =>
      writeWorkspaceFileText(conversationId, path, input),
    upload: (path, body) => uploadWorkspaceFile(conversationId, path, body),
    createDir: (path) => createWorkspaceDir(conversationId, path),
    move: (src, dst) => moveWorkspaceFile(conversationId, src, dst),
    delete: (path) => deleteWorkspaceFile(conversationId, path),
    download: (path, filename) =>
      downloadWorkspaceFile(conversationId, path, filename),
  });
  // 系统集成入口按「桌面专属能力是否存在」逐个门控（web stub 均不提供 → web 端不挂，
  // HTML 面板内为源码视图，web 的完整效果出口退化为下载）。二者相互独立：
  // - 「在浏览器打开」依赖 previewArchive（快照解压 + 系统浏览器）；
  // - 应用内「完整预览」依赖 previewApi（preview:// 独立子窗口，无需打包，按需取字节）。
  const withExtras: FileSource = { ...source };
  if (window.fsApi?.previewArchive) {
    withExtras.openInBrowser = (path) =>
      openWorkspaceInBrowser(conversationId, path);
  }
  if (window.previewApi) {
    withExtras.openInAppPreview = (path) =>
      openWorkspaceInAppPreview(conversationId, path);
  }
  return withExtras;
}

/**
 * A {@link FileSource} over a **cloud** workspace addressed by its workspace id
 * (`/v1/workspaces/{wsId}`, 文件中枢统一 Step 2) — the hub's source for cloud
 * projects. Identical shape to {@link createWorkspaceSource}; only the addressing
 * (ws id vs conversation id) differs, plus the @ index this exposes. Local
 * workspaces never use this — the hub picks `LocalRootSource` (IPC) for them (§五).
 */
export function createCloudWorkspaceSource(
  wsId: string,
  label = "工作区",
  opts?: { readonly?: boolean },
): FileSource {
  const readonly = !!opts?.readonly;
  return makeCloudSource(
    wsId,
    label,
    {
      listFiles: (recursive) => wsListFiles(wsId, recursive),
      read: (path) => wsReadFile(wsId, path),
      readForEdit: (path) => wsReadFileForEdit(wsId, path),
      writeText: (path, input) => wsWriteFileText(wsId, path, input),
      upload: (path, body) => wsUploadFile(wsId, path, body),
      createDir: (path) => wsCreateDir(wsId, path),
      move: (src, dst) => wsMoveFile(wsId, src, dst),
      delete: (path) => wsDeleteFile(wsId, path),
      download: (path, filename) => wsDownloadFile(wsId, path, filename),
      listFileIndex: () => wsListFileIndex(wsId),
    },
    readonly ? CLOUD_READONLY_CAPS : CLOUD_CAPS,
  );
}

/** Derive a single directory level from a source's recursive `listTree`
 * (cloud workspaces have no per-dir endpoint). Shared by both cloud sources. */
async function oneLevel(
  listTree: () => Promise<FileNode[]>,
  dir: string,
): Promise<FileNode[]> {
  const all = await listTree();
  const prefix = dir ? `${dir}/` : "";
  return all.filter((n) => {
    if (!n.path.startsWith(prefix)) return false;
    const rest = n.path.slice(prefix.length);
    return rest.length > 0 && !rest.includes("/");
  });
}

/**
 * Resolve a {@link WorkspaceInfo} to its {@link FileSource} — the single home for
 * "which file backend for this workspace": cloud → REST by ws id
 * ({@link createCloudWorkspaceSource}), local → desktop IPC over the bound root
 * ({@link createLocalRootSource}). Shared by the 文件 hub ({@link FileWorkbench}) and
 * the conversation side panel so the two can never drift on cloud/local selection
 * (the drift that let an agent's local file write go unseen by the cloud-only panel).
 *
 * Local resolves only on desktop (needs `window.fsApi` + a bound root); a non-empty
 * `ws.subpath` (工作区对称化 D1a) scopes the local source to that subtree under the
 * shared container root. Returns null when a local workspace can't be served here
 * (no fsApi / no root) so callers render the "在桌面端查看" degradation instead.
 */
export function resolveWorkspaceSource(
  ws: WorkspaceInfo,
  fsAvailable: boolean,
): FileSource | null {
  if (ws.location === "local") {
    if (!fsAvailable || !ws.rootId) return null;
    return createLocalRootSource(ws.rootId, ws.name, ws.subpath);
  }
  return createCloudWorkspaceSource(ws.wsId, ws.name);
}

/**
 * When the workspace list has no `conv:<id>` row yet, fall back to the same
 * local target resolution sidecar uses (`localContainerRootId` + workspace-cache
 * subpath). Returns null when no on-machine local binding exists — callers then
 * use the conversation-keyed cloud REST source.
 */
export async function resolveConversationLocalFileSource(
  conversationId: string,
): Promise<FileSource | null> {
  const target = await resolveConversationLocalTarget(conversationId);
  if (!target) return null;

  const roots = await window.fsApi.listRoots();
  const root = roots.find((r) => r.id === target.rootId);
  if (!root) return null;

  const conv = getConversations().find((c) => c.id === conversationId);
  const label = conv?.title || root.name || "工作区";
  return createLocalRootSource(target.rootId, label, target.subpath);
}
