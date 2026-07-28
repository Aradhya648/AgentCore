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
import { type ReactNode, useRef, useState } from "react";

/**
 * 对话右坞「工作区」tab 内的文件树（前端UX设计.md §十）：树 + 工具栏常驻；
 * 点文件 → 经 {@link useSidePanelStore.showFile} 开顶栏 File 内容 tab（多开并存），
 * 不再 swap 掉树。文件中枢页仍用 {@link FileWorkbench} 左右分栏。
 *
 * 单行面板头：左侧 `leading`（项目·本地/云端 chip）、中段文件操作、右侧 `trailing`（快照等）。
 */
export function FileBrowser({
  source,
  leading,
  trailing,
  emptyTreeHint,
}: {
  /** 已解析的文件源；为 null 时（本地源在本机不可用）保留工具栏（含选择器）但树/操作淡出、正文兜空态。 */
  source: FileSource | null;
  /** 工具栏最左槽（如云端/本地工作区选择器），常驻。 */
  leading?: ReactNode;
  /** 工具栏最右槽（如快照入口），常驻。 */
  trailing?: ReactNode;
  /** 文件树为空时的提示文案（对话工作区专用）。 */
  emptyTreeHint?: string;
}) {
  const showFile = useSidePanelStore((s) => s.showFile);
  const treeRef = useRef<FileTreeHandle>(null);
  const [chrome, setChrome] = useState<FileTreeChromeState>({
    uploading: false,
    hasExpanded: false,
    loading: false,
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-1.5">
        {leading}
        {leading && <div className="mx-1 h-4 w-px shrink-0 bg-border" />}

        {source?.caps.transfer && (
          <Button
            className="shrink-0 disabled:opacity-60"
            disabled={chrome.uploading}
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
                onClick={() => treeRef.current?.startCreate("file")}
                aria-label="新建文件"
              >
                <FilePlus size={14} />
              </IconButton>
            </SimpleTooltip>
            <SimpleTooltip label="新建文件夹">
              <IconButton
                onClick={() => treeRef.current?.startCreate("dir")}
                aria-label="新建文件夹"
              >
                <FolderPlus size={14} />
              </IconButton>
            </SimpleTooltip>
          </>
        )}

        <div className="min-w-0 flex-1" />

        {source && chrome.hasExpanded && (
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
              disabled={chrome.loading}
              onClick={() => treeRef.current?.refresh()}
              aria-label="刷新"
            >
              {chrome.loading ? (
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
        {source ? (
          <FileTree
            ref={treeRef}
            source={source}
            hideToolbar
            emptyText={emptyTreeHint}
            onChromeState={setChrome}
            onOpenFile={(path, name) => showFile(path, name)}
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
