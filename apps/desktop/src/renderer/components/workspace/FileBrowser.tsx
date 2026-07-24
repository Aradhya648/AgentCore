import { FileDetail } from "@/components/files/FileDetail";
import {
  FileTree,
  type FileTreeChromeState,
  type FileTreeHandle,
} from "@/components/files/FileTree";
import { EmptyHint } from "@/components/files/parts";
import { Button, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { FileSource } from "@/lib/fileSource";
import { useSidePanelStore } from "@/stores/sidePanel";
import {
  ChevronsDownUp,
  FilePlus,
  FolderPlus,
  HardDrive,
  Loader2,
  RefreshCw,
  Upload,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

/**
 * The source-agnostic file UI = a {@link FileTree} (n=1 source) that swaps to an
 * in-panel {@link FileDetail} when a file is opened. This is the **swap** variant,
 * for the *narrow* conversation side panel ({@link FilesSection}, keyed by
 * conversation) where tree + detail can't sit side by side. The cross-project 文件
 * hub uses the **split** variant ({@link FileWorkbench}) instead. Both share the leaf
 * surfaces (FileTree / FileDetail), so "which editor for this file" has one home
 * (FileDetail).
 *
 * 单行面板头：本组件持有唯一一条工具栏，左侧嵌 `leading`（工作区/云端选择器）、中段是
 * 文件操作（上传 / 新建 / 折叠 / 刷新，全部经 {@link FileTreeHandle} ref 驱动内部那棵树）、
 * 右侧嵌 `trailing`（快照 / 交接）。这条头常驻在树↔详情切换之上，故预览文件时 `leading`/
 * `trailing` 不会消失；树未挂载时文件操作淡出（disabled）。
 */
export function FileBrowser({
  source,
  leading,
  trailing,
  emptyTreeHint,
}: {
  /** 已解析的文件源；为 null 时（本地源在本机不可用）保留工具栏（含选择器）但树/操作淡出、正文兜空态。 */
  source: FileSource | null;
  /** 工具栏最左槽（如云端/本地工作区选择器），常驻、不随预览消失。 */
  leading?: ReactNode;
  /** 工具栏最右槽（如快照 / 交接入口），常驻、不随预览消失。 */
  trailing?: ReactNode;
  /** 文件树为空时的提示文案（对话工作区专用）。 */
  emptyTreeHint?: string;
}) {
  const [preview, setPreview] = useState<{ path: string; name: string } | null>(
    null,
  );
  const treeRef = useRef<FileTreeHandle>(null);
  const [chrome, setChrome] = useState<FileTreeChromeState>({
    uploading: false,
    hasExpanded: false,
    loading: false,
  });

  // 聊天里点「本回合产出文件」卡 → side-panel store 投一个预览意图，这里消费它：
  // 切到该文件的 swap 预览后清除。等 `source` 就绪才应用（本地源异步解析时不丢意图）。
  const pendingFilePreview = useSidePanelStore((s) => s.pendingFilePreview);
  const clearFilePreview = useSidePanelStore((s) => s.clearFilePreview);
  useEffect(() => {
    if (!pendingFilePreview || !source) return;
    setPreview({
      path: pendingFilePreview.path,
      name: pendingFilePreview.name,
    });
    clearFilePreview();
  }, [pendingFilePreview, source, clearFilePreview]);

  // 预览时树未挂载（被 FileDetail 取代），针对树的操作此刻无的放矢 → 淡出禁用；
  // leading / trailing 是工作区级、与具体文件无关，保持常亮。
  const treeIdle = preview !== null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-1.5">
        {leading}
        {leading && <div className="mx-1 h-4 w-px shrink-0 bg-border" />}

        {source?.caps.transfer && (
          <Button
            className="shrink-0 disabled:opacity-60"
            disabled={treeIdle || chrome.uploading}
            onClick={() => treeRef.current?.triggerUpload()}
            icon={
              chrome.uploading ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Upload size={13} />
              )
            }
          >
            上传
          </Button>
        )}
        {source && (
          <>
            <SimpleTooltip label="新建文件">
              <IconButton
                disabled={treeIdle}
                onClick={() => treeRef.current?.startCreate("file")}
                aria-label="新建文件"
              >
                <FilePlus size={14} />
              </IconButton>
            </SimpleTooltip>
            <SimpleTooltip label="新建文件夹">
              <IconButton
                disabled={treeIdle}
                onClick={() => treeRef.current?.startCreate("dir")}
                aria-label="新建文件夹"
              >
                <FolderPlus size={14} />
              </IconButton>
            </SimpleTooltip>
          </>
        )}

        <div className="min-w-0 flex-1" />

        {source && !treeIdle && chrome.hasExpanded && (
          <SimpleTooltip label="全部折叠">
            <IconButton
              onClick={() => treeRef.current?.collapseAll()}
              aria-label="全部折叠"
            >
              <ChevronsDownUp size={14} />
            </IconButton>
          </SimpleTooltip>
        )}
        {source && (
          <SimpleTooltip label="刷新">
            <IconButton
              disabled={treeIdle || chrome.loading}
              onClick={() => treeRef.current?.refresh()}
              aria-label="刷新"
            >
              {chrome.loading && !treeIdle ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
            </IconButton>
          </SimpleTooltip>
        )}

        {trailing && <div className="mx-1 h-4 w-px shrink-0 bg-border" />}
        {trailing}
      </div>

      <div className="min-h-0 flex-1">
        {preview && source ? (
          // key=path 切文件即重挂编辑器（靠卸载冲刷未保存内容）。
          <FileDetail
            key={preview.path}
            source={source}
            path={preview.path}
            name={preview.name}
            onClose={() => setPreview(null)}
          />
        ) : source ? (
          <FileTree
            ref={treeRef}
            source={source}
            hideToolbar
            emptyText={emptyTreeHint}
            onChromeState={setChrome}
            onOpenFile={(path, name) => setPreview({ path, name })}
          />
        ) : (
          // 仅本地源在本机不可用时到这（如 web 构建无 fsApi）；桌面端本地源恒可解析。
          <EmptyHint
            inline
            icon={<HardDrive size={22} className="text-muted-foreground/40" />}
            title="文件在你电脑上"
            hint="这个对话绑定了本地文件夹，请在桌面端查看其文件。"
          />
        )}
      </div>
    </div>
  );
}
