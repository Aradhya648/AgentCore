import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
} from "@/components/ui/context-menu";
import type { FileNode, FileSource } from "@/lib/fileSource";
import { baseName, isMarkdownPath, parentDir } from "@/lib/fileSource";
import { notifyActionError, notifySuccess } from "@/lib/toast";
import { openShellAtWorkspacePath } from "@/services/terminalActions";
import {
  ClipboardPaste,
  Copy,
  Download,
  ExternalLink,
  FilePlus,
  FileText,
  FileType,
  FolderPlus,
  FolderSearch,
  Pencil,
  Scissors,
  Terminal,
  Trash2,
} from "lucide-react";
import type { FileTreeRowProps } from "./FileTreeRow";

/** The shared right-click menu for a file/folder row. */
export function FileTreeRowMenu({
  node,
  source,
  hasClipboard,
  onContextCreate,
  onStartRename,
  onDelete,
  onOpenFile,
  onCopy,
  onCut,
  onPaste,
  onReloadDir,
}: { node: FileNode; source: FileSource } & Pick<
  FileTreeRowProps,
  | "hasClipboard"
  | "onContextCreate"
  | "onStartRename"
  | "onDelete"
  | "onOpenFile"
  | "onCopy"
  | "onCut"
  | "onPaste"
  | "onReloadDir"
>) {
  // 系统集成项只在源实现了对应方法时出现（本地源有、云端源无）——靠「方法是否存在」门控，
  // 组件内不按源 if 分支。「用默认程序打开」仅给文件（对目录而言就是再次定位，与 reveal 重复）。
  const canReveal = !!source.revealInOsFileManager;
  const canOpenShell = !!source.openShellAtPath;
  const canOpenExternal = !node.isDir && !!source.openWithOsDefaultApp;
  const canCopyPath = !!source.copyOsPath;
  const hasOsGroup =
    canReveal || canOpenShell || canOpenExternal || canCopyPath;
  // 复制走可选 copy（本地源有、云端源无）；剪切走必备 move（全源可用）；粘贴仅文件夹行 +
  // 剪贴板非空时出现（粘贴进该文件夹）。
  const canCopy = !!source.copy;

  const reveal = async () => {
    try {
      await source.revealInOsFileManager?.(node.path);
    } catch (e) {
      notifyActionError("无法在资源管理器中显示", e);
    }
  };
  const openShell = async () => {
    await openShellAtWorkspacePath(source, node.path, node.isDir);
  };
  const openExternal = async () => {
    try {
      await source.openWithOsDefaultApp?.(node.path);
    } catch (e) {
      notifyActionError("无法用默认程序打开", e);
    }
  };
  const copyPath = async () => {
    try {
      await source.copyOsPath?.(node.path);
      notifySuccess("已复制路径");
    } catch (e) {
      notifyActionError("复制路径失败", e);
    }
  };

  // Groups separated systematically (a leading separator only when both sides are
  // non-empty) so no group ever yields a double rule. The primary group (dir →
  // 新建; file → 打开/下载) is always present, so 系统集成 / 编辑 just prefix a rule.
  // `caps.edit === false` (e.g. shared-space viewer) hides mutate actions; download
  // still rides on `caps.transfer`.
  const canMutate = source.caps.edit;
  return (
    <ContextMenuContent className="min-w-36">
      {node.isDir ? (
        canMutate ? (
          <>
            <ContextMenuItem
              onSelect={() => onContextCreate(node.path, "file")}
            >
              <FilePlus size={14} className="shrink-0" />
              <span className="flex-1 truncate">新建文件</span>
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => onContextCreate(node.path, "dir")}>
              <FolderPlus size={14} className="shrink-0" />
              <span className="flex-1 truncate">新建文件夹</span>
            </ContextMenuItem>
          </>
        ) : null
      ) : (
        <>
          {source.caps.transfer && source.download && (
            <ContextMenuItem
              onSelect={() =>
                void source
                  .download?.(node.path, node.name)
                  .catch((e) => notifyActionError("下载失败", e))
              }
            >
              <Download size={14} className="shrink-0" />
              <span className="flex-1 truncate">下载</span>
            </ContextMenuItem>
          )}
          <ContextMenuItem onSelect={() => onOpenFile(node.path, node.name)}>
            <FileText size={14} className="shrink-0" />
            <span className="flex-1 truncate">打开</span>
          </ContextMenuItem>
          {canMutate &&
            isMarkdownPath(node.path) &&
            source.exportMdToDocx && (
              <ContextMenuItem
                onSelect={() => {
                  void (async () => {
                    try {
                      const result = await source.exportMdToDocx?.(node.path);
                      if (!result) return;
                      onReloadDir(parentDir(node.path));
                      if (result.warnings.length > 0) {
                        notifySuccess(
                          `已导出 ${baseName(result.path)}（${result.warnings.length} 条警告）`,
                        );
                      } else {
                        notifySuccess(`已导出 ${baseName(result.path)}`);
                      }
                    } catch (e) {
                      notifyActionError("导出 Word 失败", e);
                    }
                  })();
                }}
              >
                <FileType size={14} className="shrink-0" />
                <span className="flex-1 truncate">导出 Word</span>
              </ContextMenuItem>
            )}
        </>
      )}
      {hasOsGroup && (
        <>
          <ContextMenuSeparator />
          {canOpenExternal && (
            <ContextMenuItem onSelect={() => void openExternal()}>
              <ExternalLink size={14} className="shrink-0" />
              <span className="flex-1 truncate">用默认程序打开</span>
            </ContextMenuItem>
          )}
          {canReveal && (
            <ContextMenuItem onSelect={() => void reveal()}>
              <FolderSearch size={14} className="shrink-0" />
              <span className="flex-1 truncate">在资源管理器中显示</span>
            </ContextMenuItem>
          )}
          {canOpenShell && (
            <ContextMenuItem onSelect={() => void openShell()}>
              <Terminal size={14} className="shrink-0" />
              <span className="flex-1 truncate">在终端打开</span>
            </ContextMenuItem>
          )}
          {canCopyPath && (
            <ContextMenuItem onSelect={() => void copyPath()}>
              <Copy size={14} className="shrink-0" />
              <span className="flex-1 truncate">复制路径</span>
            </ContextMenuItem>
          )}
        </>
      )}
      {canMutate && (
        <>
          <ContextMenuSeparator />
          {canCopy && (
            <ContextMenuItem onSelect={() => onCopy(node.path)}>
              <Copy size={14} className="shrink-0" />
              <span className="flex-1 truncate">复制</span>
            </ContextMenuItem>
          )}
          <ContextMenuItem onSelect={() => onCut(node.path)}>
            <Scissors size={14} className="shrink-0" />
            <span className="flex-1 truncate">剪切</span>
          </ContextMenuItem>
          {node.isDir && hasClipboard && (
            <ContextMenuItem onSelect={() => onPaste(node.path)}>
              <ClipboardPaste size={14} className="shrink-0" />
              <span className="flex-1 truncate">粘贴到此文件夹</span>
            </ContextMenuItem>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem onSelect={() => onStartRename(node.path)}>
            <Pencil size={14} className="shrink-0" />
            <span className="flex-1 truncate">重命名</span>
          </ContextMenuItem>
          <ContextMenuItem
            variant="danger"
            onSelect={() => void onDelete(node)}
          >
            <Trash2 size={14} className="shrink-0" />
            <span className="flex-1 truncate">删除</span>
          </ContextMenuItem>
        </>
      )}
    </ContextMenuContent>
  );
}
