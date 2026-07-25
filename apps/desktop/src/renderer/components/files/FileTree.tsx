import { Button, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  type FileNode,
  type FileSource,
  baseName,
  joinPath,
  parentDir,
} from "@/lib/fileSource";
import { notifyActionError, notifyError } from "@/lib/toast";
import {
  ChevronsDownUp,
  FilePlus,
  FileText,
  FolderPlus,
  Loader2,
  RefreshCw,
  Upload,
} from "lucide-react";
import type React from "react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { InlineCreateRow } from "./FileTreeInline";
import { FileTreeRow } from "./FileTreeRow";
import { dedupeName } from "./dedupeName";
import { DRAG_MIME, parseDragPayload } from "./fileTreeDrag";
import { loadExpanded, saveExpanded } from "./fileTreeExpanded";
import type {
  ClipboardEntry,
  FileTreeChromeState,
  FileTreeHandle,
} from "./fileTreeTypes";
import { Centered, EmptyHint, InlineError } from "./parts";
import { useFileTreeData } from "./useFileTreeData";

export { dedupeName } from "./dedupeName";
export type { FileTreeChromeState, FileTreeHandle } from "./fileTreeTypes";

/**
 * The unified file tree for any {@link FileSource} (文件中枢统一 Step 0) — the one
 * tree that backs both the Files page (a local OS root) and the conversation
 * workspace panel (the server workspace). Capabilities gate the chrome: upload
 * appears only when the source can transfer bytes; live updates only when it can
 * watch. Interaction model is converged on inline create/rename + a right-click
 * context menu + drag-to-move (within the source), with per-source persisted
 * fold state. The container owns where a clicked file opens (via `onOpenFile`).
 */
interface FileTreeProps {
  source: FileSource;
  onOpenFile: (path: string, name: string) => void;
  activePath?: string | null;
  headerExtra?: React.ReactNode;
  /** 隐藏自带工具栏 + 自身高度/滚动（嵌入式多根堆叠用，由外层统一滚动）。 */
  chrome?: boolean;
  /**
   * 仅隐藏自带工具栏、但保留自身高度/滚动（chrome 模式下由外层接管工具栏、
   * 把文件操作经 {@link FileTreeHandle} ref 驱动；侧栏单行面板头用）。
   */
  hideToolbar?: boolean;
  /**
   * 工具栏相关状态变更回调（外置工具栏据此响应式渲染上传/折叠/刷新态）。
   * 调用方应传**稳定引用**（如 useState 的 setter），否则会按渲染抖动。
   */
  onChromeState?: (state: FileTreeChromeState) => void;
  /** 每行额外左内边距，用于把整棵树嵌套在某个标题（工作区根）之下。 */
  indent?: number;
  /** 嵌入模式（chrome=false）下根为空时的提示文案（默认「空文件夹」）。 */
  emptyText?: string;
}

export const FileTree = forwardRef<FileTreeHandle, FileTreeProps>(
  function FileTree(
    {
      source,
      onOpenFile,
      activePath = null,
      headerExtra,
      chrome = true,
      hideToolbar = false,
      onChromeState,
      indent = 0,
      emptyText = "空文件夹",
    },
    ref,
  ) {
    const data = useFileTreeData(source);
    const [expanded, setExpanded] = useState<Set<string>>(() =>
      loadExpanded(source.id),
    );
    const [creating, setCreating] = useState<{
      dir: string;
      kind: "file" | "dir";
    } | null>(null);
    const [renaming, setRenaming] = useState<string | null>(null);
    const [dropTarget, setDropTarget] = useState<string | null>(null);
    const [uploading, setUploading] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    // 键盘焦点节点（复制/剪切/粘贴的作用对象）与剪贴板，均限本树内（与拖拽移动同源约束一致）。
    const [selected, setSelected] = useState<{
      path: string;
      isDir: boolean;
    } | null>(null);
    const [clipboard, setClipboard] = useState<ClipboardEntry | null>(null);
    const uploadRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
      setExpanded(loadExpanded(source.id));
      setSelected(null);
      setClipboard(null);
    }, [source.id]);

    // Live updates: watch the root + every expanded dir (local FS only).
    useEffect(() => {
      const watch = source.watch;
      if (!watch || !source.caps.watch) return;
      const offs = ["", ...expanded].map((dir) =>
        watch(dir, () => data.reload(dir)),
      );
      return () => {
        for (const off of offs) off();
      };
    }, [source, expanded, data]);

    const toggle = useCallback(
      (dir: string) => {
        setExpanded((prev) => {
          const next = new Set(prev);
          if (next.has(dir)) next.delete(dir);
          else {
            next.add(dir);
            data.ensureDir(dir);
          }
          saveExpanded(source.id, next);
          return next;
        });
      },
      [data, source.id],
    );

    const collapseAll = useCallback(() => {
      saveExpanded(source.id, new Set());
      setExpanded(new Set());
    }, [source.id]);

    const refresh = useCallback(() => {
      data.reload("");
      for (const dir of expanded) data.reload(dir);
    }, [data, expanded]);

    const openCreate = useCallback(
      (dir: string, kind: "file" | "dir") => {
        if (dir !== "") {
          setExpanded((prev) => {
            if (prev.has(dir)) return prev;
            const next = new Set(prev).add(dir);
            data.ensureDir(dir);
            saveExpanded(source.id, next);
            return next;
          });
        }
        setCreating({ dir, kind });
      },
      [data, source.id],
    );

    const submitCreate = useCallback(
      async (rawName: string) => {
        const target = creating;
        setCreating(null);
        if (!target) return;
        const name = rawName.trim().replace(/^\/+|\/+$/g, "");
        if (!name || name.includes("/")) return;
        const path = joinPath(target.dir, name);
        try {
          if (target.kind === "dir") await source.mkdir(path);
          else await source.createFile(path);
          data.reload(target.dir);
          if (target.kind === "file") onOpenFile(path, name);
        } catch {
          notifyError("已存在同名文件或文件夹，或创建失败");
        }
      },
      [creating, source, data, onOpenFile],
    );

    const submitRename = useCallback(
      async (path: string, rawName: string) => {
        setRenaming(null);
        const name = rawName.trim();
        if (!name || name === baseName(path)) return;
        if (name.includes("/")) {
          notifyError("名称不能包含「/」");
          return;
        }
        const dst = joinPath(parentDir(path), name);
        try {
          await source.move(path, dst);
          data.reload(parentDir(path));
        } catch {
          notifyError("已存在同名文件，或重命名失败");
        }
      },
      [source, data],
    );

    const remove = useCallback(
      async (node: FileNode) => {
        const what = node.isDir ? "文件夹及其全部内容" : "文件";
        if (
          !window.confirm(`确定删除${what}「${node.name}」？此操作不可撤销。`)
        ) {
          return;
        }
        try {
          await source.delete(node.path);
          data.reload(parentDir(node.path));
        } catch {
          notifyError("删除失败");
        }
      },
      [source, data],
    );

    // Move `src` into `destDir` (""=root), keeping its name. Guards against a no-op
    // and against dropping a folder into its own subtree.
    const moveInto = useCallback(
      async (src: string, destDir: string) => {
        const dst = joinPath(destDir, baseName(src));
        if (dst === src) return;
        if (destDir === src || destDir.startsWith(`${src}/`)) return;
        try {
          await source.move(src, dst);
          data.reload(parentDir(src));
          data.reload(destDir);
        } catch {
          notifyError("目标位置已存在同名文件，或移动失败");
        }
      },
      [source, data],
    );

    const upload = useCallback(
      async (files: FileList | null, destDir = "") => {
        if (!files || files.length === 0 || !source.writeBytes) return;
        setUploading(true);
        try {
          for (const file of Array.from(files)) {
            await source.writeBytes(joinPath(destDir, file.name), file);
          }
          data.reload(destDir);
        } catch {
          notifyError("上传失败");
        } finally {
          setUploading(false);
        }
      },
      [source, data],
    );

    const onSelect = useCallback((node: FileNode) => {
      setSelected({ path: node.path, isDir: node.isDir });
    }, []);

    const doCopy = useCallback(
      (path: string) => {
        if (source.copy) setClipboard({ op: "copy", path });
      },
      [source],
    );

    const doCut = useCallback((path: string) => {
      setClipboard({ op: "cut", path });
    }, []);

    // 把目标目录展开（若折叠），让粘贴结果立即可见；随后由调用方 reload。
    const revealDir = useCallback(
      (dir: string) => {
        if (dir === "") return;
        setExpanded((prev) => {
          if (prev.has(dir)) return prev;
          const next = new Set(prev).add(dir);
          data.ensureDir(dir);
          saveExpanded(source.id, next);
          return next;
        });
      },
      [data, source.id],
    );

    // 把剪贴板内容粘贴进 destDir（""=根）。剪切走必备的 move（全源可用，一次性）；复制走可选
    // copy（本地源），名字按目标目录现有项去重（副本 / 副本 2…），可重复粘贴。
    const doPaste = useCallback(
      async (destDir: string) => {
        const clip = clipboard;
        if (!clip) return;
        if (destDir === clip.path || destDir.startsWith(`${clip.path}/`)) {
          notifyActionError("无法粘贴", new Error("不能粘贴到自身或其子目录"));
          return;
        }
        try {
          const siblings = await source.listDir(destDir);
          const names = new Set(siblings.map((n) => n.name));
          const origName = baseName(clip.path);
          if (clip.op === "cut") {
            if (parentDir(clip.path) === destDir) return; // 原地剪切粘贴 = 空操作
            if (names.has(origName)) {
              notifyActionError("无法粘贴", new Error("目标位置已存在同名项"));
              return;
            }
            await source.move(clip.path, joinPath(destDir, origName));
            setClipboard(null); // 剪切是一次性的
            data.reload(parentDir(clip.path));
          } else {
            if (!source.copy) return;
            await source.copy(
              clip.path,
              joinPath(destDir, dedupeName(origName, names)),
            );
            // 复制保留剪贴板，可重复粘贴（每次对最新清单去重）。
          }
          revealDir(destDir);
          data.reload(destDir);
        } catch (e) {
          notifyActionError("粘贴失败", e);
        }
      },
      [clipboard, source, data, revealDir],
    );

    // Delete/Backspace 删选中项；Ctrl/Cmd + C/X/V 剪贴板。仅当焦点在树内（行按钮）时
    // 触发；输入框 / 创建·重命名态让出；有选区时让出原生文本复制。
    const onTreeKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (creating || renaming) return;
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        if (
          (e.key === "Delete" || e.key === "Backspace") &&
          !e.ctrlKey &&
          !e.metaKey &&
          !e.altKey
        ) {
          if (selected) {
            e.preventDefault();
            void remove({
              path: selected.path,
              name: baseName(selected.path),
              isDir: selected.isDir,
            });
          }
          return;
        }
        if (!(e.ctrlKey || e.metaKey)) return;
        if (window.getSelection()?.toString()) return;
        const key = e.key.toLowerCase();
        if (key === "c") {
          if (selected && source.copy) {
            e.preventDefault();
            doCopy(selected.path);
          }
        } else if (key === "x") {
          if (selected) {
            e.preventDefault();
            doCut(selected.path);
          }
        } else if (key === "v" && clipboard) {
          e.preventDefault();
          const destDir = selected
            ? selected.isDir
              ? selected.path
              : parentDir(selected.path)
            : "";
          void doPaste(destDir);
        }
      },
      [
        creating,
        renaming,
        selected,
        clipboard,
        source,
        remove,
        doCopy,
        doCut,
        doPaste,
      ],
    );

    const rootStatus = data.statusOf("");
    const rootChildren = data.childrenOf("");

    useImperativeHandle(
      ref,
      () => ({
        startCreate: (kind) => openCreate("", kind),
        refresh,
        triggerUpload: () => uploadRef.current?.click(),
        collapseAll,
      }),
      [openCreate, refresh, collapseAll],
    );

    // Mirror toolbar-relevant state up so an external toolbar (e.g. the side
    // panel's single header row) can render upload/collapse/refresh reactively
    // while still driving the actions through the ref.
    useEffect(() => {
      onChromeState?.({
        uploading,
        hasExpanded: expanded.size > 0,
        loading: rootStatus === "loading",
      });
    }, [onChromeState, uploading, expanded, rootStatus]);

    const canMutate = source.caps.edit;
    const canUpload = source.caps.transfer && canMutate;

    const onDragOverRoot = (e: React.DragEvent) => {
      if (e.dataTransfer.types.includes(DRAG_MIME)) setDropTarget(null);
      else if (canUpload) {
        e.preventDefault();
        setDragOver(true);
      }
    };
    const onDropRoot = (e: React.DragEvent) => {
      setDragOver(false);
      setDropTarget(null);
      const raw = e.dataTransfer.getData(DRAG_MIME);
      if (raw) {
        e.preventDefault();
        if (!canMutate) return;
        const p = parseDragPayload(raw);
        if (p && p.sourceId === source.id) void moveInto(p.path, "");
        return;
      }
      if (canUpload && e.dataTransfer.files.length > 0) {
        e.preventDefault();
        void upload(e.dataTransfer.files, "");
      }
    };

    // 隐藏的上传 input 始终渲染（即使无工具栏的嵌入模式也要能经 triggerUpload 触发）。
    const uploadInput = canUpload ? (
      <input
        ref={uploadRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          void upload(e.target.files, "");
          e.target.value = "";
        }}
      />
    ) : null;

    // 加载 / 错误 / 空：有 chrome（独占面板）时居中铺满；嵌入堆叠时收成左对齐小行。
    const loadingEl = chrome ? (
      <Centered>
        <Loader2 size={18} className="animate-spin text-muted-foreground/50" />
      </Centered>
    ) : (
      <div
        className="flex items-center gap-1.5 py-2 text-xs text-muted-foreground"
        style={{ paddingLeft: indent + 8 }}
      >
        <Loader2 size={12} className="animate-spin" />
        加载中…
      </div>
    );

    const errorEl = chrome ? (
      <InlineError onRetry={() => data.reload("")} />
    ) : (
      <div
        className="flex items-center gap-2 py-2 text-xs text-destructive/80"
        style={{ paddingLeft: indent + 8 }}
      >
        加载失败
        <Button
          variant="ghost"
          onClick={() => data.reload("")}
          className="h-auto px-0 py-0 underline-offset-2 hover:underline"
        >
          重试
        </Button>
      </div>
    );

    const emptyEl = chrome ? (
      <EmptyHint
        inline
        icon={<FileText size={22} className="text-muted-foreground/40" />}
        title="暂无文件"
        hint={
          canUpload
            ? "拖拽文件到此处，或点「上传」「新建」开始。"
            : canMutate
              ? "点「新建」开始，或在此文件夹放入文件。"
              : "此工作区为只读。"
        }
      />
    ) : (
      <div
        className="py-1 text-xs text-muted-foreground/60"
        style={{ paddingLeft: indent + 8 }}
      >
        {emptyText}
      </div>
    );

    const body =
      rootStatus === "error" ? (
        errorEl
      ) : rootChildren === undefined ? (
        loadingEl
      ) : rootChildren.length === 0 && !creating ? (
        emptyEl
      ) : (
        <ul>
          {creating?.dir === "" && (
            <InlineCreateRow
              kind={creating.kind}
              depth={0}
              indentBase={indent}
              onSubmit={submitCreate}
              onCancel={() => setCreating(null)}
            />
          )}
          {(rootChildren ?? []).map((node) => (
            <FileTreeRow
              key={node.path}
              node={node}
              depth={0}
              indentBase={indent}
              source={source}
              data={data}
              expanded={expanded}
              activePath={activePath}
              creating={creating}
              renaming={renaming}
              dropTarget={dropTarget}
              selectedPath={selected?.path ?? null}
              cutPath={clipboard?.op === "cut" ? clipboard.path : null}
              hasClipboard={clipboard !== null}
              onToggle={toggle}
              onOpenFile={onOpenFile}
              onSelect={onSelect}
              onContextCreate={openCreate}
              onStartRename={setRenaming}
              onSubmitRename={submitRename}
              onCancelRename={() => setRenaming(null)}
              onSubmitCreate={submitCreate}
              onCancelCreate={() => setCreating(null)}
              onDelete={remove}
              onCopy={doCopy}
              onCut={doCut}
              onPaste={doPaste}
              onMoveInto={moveInto}
              onUpload={upload}
              onDropTarget={setDropTarget}
              onReloadDir={(dir) => data.reload(dir)}
            />
          ))}
        </ul>
      );

    // 嵌入模式：无工具栏、无自身高度/滚动，撑内容高度；横向内边距由外层左栏统一给。
    if (!chrome) {
      return (
        <div
          onKeyDown={onTreeKeyDown}
          onDragOver={onDragOverRoot}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDropRoot}
        >
          {uploadInput}
          {body}
        </div>
      );
    }

    return (
      <div
        className="flex h-full flex-col"
        onKeyDown={onTreeKeyDown}
        onDragOver={onDragOverRoot}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDropRoot}
      >
        {uploadInput}
        {!hideToolbar && (
          <div className="flex shrink-0 items-center gap-1 px-3 py-2">
            {canUpload && (
              <Button
                className="disabled:opacity-60"
                disabled={uploading}
                onClick={() => uploadRef.current?.click()}
                icon={
                  uploading ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Upload size={13} />
                  )
                }
              >
                上传
              </Button>
            )}
            {canMutate && (
              <>
                <SimpleTooltip label="新建文件">
                  <IconButton
                    onClick={() => openCreate("", "file")}
                    aria-label="新建文件"
                  >
                    <FilePlus size={14} />
                  </IconButton>
                </SimpleTooltip>
                <SimpleTooltip label="新建文件夹">
                  <IconButton
                    onClick={() => openCreate("", "dir")}
                    aria-label="新建文件夹"
                  >
                    <FolderPlus size={14} />
                  </IconButton>
                </SimpleTooltip>
              </>
            )}
            <div className="flex-1" />
            {expanded.size > 0 && (
              <SimpleTooltip label="全部折叠">
                <IconButton onClick={collapseAll} aria-label="全部折叠">
                  <ChevronsDownUp size={14} />
                </IconButton>
              </SimpleTooltip>
            )}
            <SimpleTooltip label="刷新">
              <IconButton
                disabled={rootStatus === "loading"}
                onClick={refresh}
                aria-label="刷新"
              >
                {rootStatus === "loading" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <RefreshCw size={14} />
                )}
              </IconButton>
            </SimpleTooltip>
            {headerExtra}
          </div>
        )}

        {dragOver && canUpload && (
          <div className="mx-3 mb-2 shrink-0 rounded-lg border border-dashed border-primary bg-primary/5 px-3 py-4 text-center text-xs text-primary">
            松开以上传到此处
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">{body}</div>
      </div>
    );
  },
);
