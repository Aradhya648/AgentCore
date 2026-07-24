import { getTokens } from "@/api/client";
import {
  type DownloadedFile,
  type FileNode,
  type WorkspaceFileEntry,
  buildTree,
} from "@/api/workspace";
import { Modal } from "@/components/Modal";
import { canShareFiles, downloadBlob, shareOrDownloadFile } from "@/lib/share";
import {
  countDescendantFiles,
  stageDirCaption,
  stageDirMeta,
} from "@/lib/stageDirs";
// Shared workspace file browser (手机端布局重构 · 文件浏览复用).
//
// The crumbs + in-memory folder nav + full-screen previewer, extracted so both file surfaces
// reuse one implementation: the per-conversation files page (/c/:id/files, reached from a
// chat) and the 文件 tab's per-workspace browse (/files/:wsId). They differ only in addressing
// (conversation alias vs first-class workspace id) and the page chrome (header / back target /
// upload) — that stays in each page; the data source is injected as `source`.
//
// `cwd` is CONTROLLED by the parent so the page's header「上传」knows the target folder; the
// parent resets it to "" when the workspace changes and leaves it alone on an upload-triggered
// `reloadKey` bump (stay in the current folder after a write). The list endpoint only returns
// 顶层 or 整树, so the whole tree is fetched once (recursive) and walked in memory — one
// round-trip, instant folder nav (same as the original per-conversation browser).
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

/** The injected data source: how to list the tree and fetch one file's bytes. */
export interface FileBrowserSource {
  list: () => Promise<WorkspaceFileEntry[]>;
  download: (path: string) => Promise<DownloadedFile>;
}

const IMAGE_EXT = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "bmp",
  "ico",
  "avif",
]);
const TEXT_EXT = new Set([
  "txt",
  "md",
  "markdown",
  "json",
  "jsonl",
  "js",
  "jsx",
  "ts",
  "tsx",
  "mjs",
  "cjs",
  "css",
  "scss",
  "less",
  "html",
  "htm",
  "xml",
  "yaml",
  "yml",
  "toml",
  "ini",
  "cfg",
  "conf",
  "csv",
  "tsv",
  "log",
  "py",
  "rb",
  "go",
  "rs",
  "java",
  "kt",
  "c",
  "h",
  "cpp",
  "hpp",
  "cc",
  "sh",
  "bash",
  "zsh",
  "sql",
  "env",
  "gitignore",
  "dockerfile",
  "makefile",
  "vue",
  "svelte",
  "php",
  "lua",
  "r",
  "dart",
  "swift",
  "scala",
  "pl",
  "ps1",
  "bat",
  "properties",
  "gradle",
]);
const TEXT_PREVIEW_MAX = 512 * 1024;

function ext(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : name.toLowerCase();
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileBrowser({
  source,
  cwd,
  onCwdChange,
  reloadKey = 0,
  emptyHint = "（空）",
  openPath = null,
}: {
  source: FileBrowserSource;
  cwd: string;
  onCwdChange: (cwd: string) => void;
  reloadKey?: number;
  emptyHint?: string;
  /** 深链：树加载后自动打开该路径文件的预览并落到其所在目录（聊天「本回合产出文件」卡的
   *  一键直达）。只消费一次；树里找不到则按路径直接构造节点（下载失败由预览器兜底报错）。 */
  openPath?: string | null;
}) {
  const navigate = useNavigate();
  const [tree, setTree] = useState<Map<string, FileNode[]> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<FileNode | null>(null);
  const openedRef = useRef(false);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadKey is an intentional manual-reload trigger — bumping it re-lists even though the body doesn't read it
  useEffect(() => {
    let cancelled = false;
    setTree(null);
    setError(null);
    source
      .list()
      .then((entries) => {
        if (!cancelled) setTree(buildTree(entries));
      })
      .catch((e) => {
        if (cancelled) return;
        // A cleared token → the api layer couldn't refresh; route to login (mirrors the
        // other pages' guard) rather than showing a load error.
        if (!getTokens()) {
          navigate("/login", { replace: true });
          return;
        }
        setError(e instanceof Error ? e.message : "加载文件列表失败");
        setTree(new Map());
      });
    return () => {
      cancelled = true;
    };
  }, [source, reloadKey, navigate]);

  // 一键直达：树就绪后，把请求的文件落到其目录并打开预览。只跑一次（openedRef 守门），
  // 避免折回目录/二次打开。找不到精确节点就按路径构造一个（预览器自行下载、失败兜底）。
  useEffect(() => {
    if (!openPath || openedRef.current || tree === null) return;
    openedRef.current = true;
    const slash = openPath.lastIndexOf("/");
    const dir = slash >= 0 ? openPath.slice(0, slash) : "";
    const name = openPath.slice(slash + 1) || openPath;
    const node = (tree.get(dir) ?? []).find(
      (n) => !n.isDir && n.path === openPath,
    ) ?? { name, path: openPath, isDir: false };
    if (dir) onCwdChange(dir);
    setViewing(node);
  }, [openPath, tree, onCwdChange]);

  const children = tree?.get(cwd) ?? [];
  const crumbs = cwd ? cwd.split("/") : [];

  return (
    <>
      {tree !== null && (
        <div className="crumbs">
          <button
            type="button"
            className="crumb"
            disabled={cwd === ""}
            onClick={() => onCwdChange("")}
          >
            根目录
          </button>
          {crumbs.map((seg, i) => {
            const full = crumbs.slice(0, i + 1).join("/");
            const last = i === crumbs.length - 1;
            return (
              <span key={full} className="crumb-seg">
                <span className="crumb-sep">/</span>
                <button
                  type="button"
                  className="crumb"
                  disabled={last}
                  onClick={() => onCwdChange(full)}
                >
                  {seg}
                </button>
              </span>
            );
          })}
        </div>
      )}

      <div className="list">
        {tree === null && !error && <p className="muted hint">加载中…</p>}
        {tree !== null && cwd === "" && children.length === 0 && !error && (
          <p className="muted hint">{emptyHint}</p>
        )}
        {tree !== null && cwd !== "" && children.length === 0 && (
          <p className="muted hint">（空文件夹）</p>
        )}
        {children.map((node) => {
          const stage =
            cwd === "" && node.isDir ? stageDirMeta(node.path) : null;
          const stageCaption =
            stage && tree
              ? stageDirCaption(
                  stage,
                  countDescendantFiles(node.path, (d) => tree.get(d)),
                )
              : null;
          return node.isDir ? (
            <button
              key={node.path}
              type="button"
              className="file-row"
              title={stage?.tooltip}
              onClick={() => onCwdChange(node.path)}
            >
              <span className="file-icon" aria-hidden>
                ▸
              </span>
              <span className="file-name">{node.name}</span>
              {stageCaption && (
                <span className="file-tag" title={stage?.tooltip}>
                  {stageCaption}
                </span>
              )}
              <span className="file-chevron" aria-hidden>
                ›
              </span>
            </button>
          ) : (
            <button
              key={node.path}
              type="button"
              className="file-row"
              onClick={() => setViewing(node)}
            >
              <span className="file-icon file-icon-doc" aria-hidden>
                ·
              </span>
              <span className="file-name">{node.name}</span>
            </button>
          );
        })}
      </div>

      {error && <div className="error bar">{error}</div>}

      {viewing && (
        <FileViewer
          node={viewing}
          download={source.download}
          onClose={() => setViewing(null)}
        />
      )}
    </>
  );
}

type View =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "image"; url: string }
  | { kind: "text"; text: string }
  | { kind: "binary"; size: number };

/** Full-screen preview for one file: text in a <pre>, images inline, anything else a
 *  download-only notice. Bytes are fetched once via the injected `download`; the 下载/分享
 *  actions reuse them (Web Share where the OS sheet can take a file, else browser download). */
function FileViewer({
  node,
  download,
  onClose,
}: {
  node: FileNode;
  download: (path: string) => Promise<DownloadedFile>;
  onClose: () => void;
}) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [file, setFile] = useState<DownloadedFile | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setView({ kind: "loading" });
    setFile(null);
    download(node.path)
      .then(async (f) => {
        if (cancelled) return;
        setFile(f);
        const e = ext(node.name);
        const isImage = f.contentType.startsWith("image/") || IMAGE_EXT.has(e);
        const isText =
          f.contentType.startsWith("text/") ||
          /json|javascript|xml|yaml|toml|csv/.test(f.contentType) ||
          TEXT_EXT.has(e);
        if (isImage) {
          objectUrl = URL.createObjectURL(f.blob);
          setView({ kind: "image", url: objectUrl });
        } else if (isText && f.blob.size <= TEXT_PREVIEW_MAX) {
          const text = await f.blob.text();
          if (!cancelled) setView({ kind: "text", text });
        } else {
          setView({ kind: "binary", size: f.blob.size });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setView({
          kind: "error",
          message: err instanceof Error ? err.message : "下载失败",
        });
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [node, download]);

  // Capability is stable for the session; compute once so the 分享 action only shows
  // where the OS sheet can actually take a file (else 下载 is the path).
  const sharable = canShareFiles();

  function save() {
    if (file) downloadBlob(file.blob, file.filename);
  }

  async function share() {
    if (file)
      await shareOrDownloadFile(file.blob, file.filename, file.contentType);
  }

  return (
    <Modal className="viewer" onClose={onClose} label={node.name}>
      <header className="bar">
        <button type="button" className="link" onClick={onClose}>
          ← 文件
        </button>
        <span className="viewer-name">{node.name}</span>
        <span className="bar-right">
          {sharable && (
            <button
              type="button"
              className="link"
              onClick={() => void share()}
              disabled={!file}
            >
              分享
            </button>
          )}
          <button
            type="button"
            className="link"
            onClick={save}
            disabled={!file}
          >
            下载
          </button>
        </span>
      </header>
      <div className="viewer-body">
        {view.kind === "loading" && <p className="muted hint">加载中…</p>}
        {view.kind === "error" && <p className="error hint">{view.message}</p>}
        {view.kind === "image" && (
          <img className="viewer-img" src={view.url} alt={node.name} />
        )}
        {view.kind === "text" && <pre className="viewer-text">{view.text}</pre>}
        {view.kind === "binary" && (
          <p className="muted hint">
            无法预览此文件类型（{formatSize(view.size)}
            ）。点右上角「下载」保存。
          </p>
        )}
      </div>
    </Modal>
  );
}
