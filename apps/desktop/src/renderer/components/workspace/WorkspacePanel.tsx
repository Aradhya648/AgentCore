import { EmptyHint, IconButton } from "@/components/files/parts";
import { Button } from "@/components/ui";
import { useConversationFileSource } from "@/hooks/useConversationFileSource";
import { useConversationWorkspace } from "@/hooks/useWorkspaces";
import { hasLocalFiles } from "@/lib/capabilities";
import { notifyActionError, notifySuccess } from "@/lib/toast";
import {
  exportWorkspaceToLocal,
  exportWorkspaceZip,
} from "@/services/workspace";
import { useConversationStore } from "@/stores/conversation";
import {
  Download,
  FolderDown,
  FolderOpen,
  History,
  Loader2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { FilesSection } from "./FilesSection";
import { SharedMountsSection } from "./SharedMountsSection";
import { SnapshotsSection } from "./SnapshotsSection";
import { WorkspaceClientTools } from "./WorkspaceClientTools";
import { WorkspaceModeBar } from "./WorkspaceModeBar";

/**
 * Workspace mode of the conversation side panel — the file-in/out + persistence
 * surface for a conversation's project space (双模式工作区). Files are the panel's
 * always-on body; this view injects two workspace-level affordances into the files
 * toolbar's single header row (FileBrowser owns that row): 云端/本地选择器 (leading)
 * plus one on-demand entry (trailing) — 快照 opens a slide-over (backup / kept
 * versions / restore). The shell (SidePanel) owns the frame / resize / close.
 *
 * 交接（把活交给云端团队）已下沉为对话时间线里的「后台云端任务」卡（交接「方案 B」/
 * `BackgroundTaskCard`），完成后就地内联评审应用，不再占用工作区侧栏的独立入口。
 *
 * A draft conversation (no id yet) has no server workspace, so it shows an empty
 * hint until the first turn persists it.
 */
export function WorkspaceMode() {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const [snapshotsOpen, setSnapshotsOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  // 与文件中枢同一份数据 + 同一个解析器：对话→其工作区(WorkspaceInfo)→FileSource。本地走桌面
  // IPC、云端走 REST，故 Agent 在本地写的文件这里也能列出（修复「写在本地、读在云端」）。
  const ws = useConversationWorkspace(conversationId);
  const fsAvailable = hasLocalFiles();
  const source = useConversationFileSource(conversationId);

  useEffect(() => {
    const sourceKind: "local" | "cloud" | null =
      source === null
        ? null
        : source.id.startsWith("local:")
          ? "local"
          : "cloud";
    console.warn(
      `[FilePreview] workspace source selection ${JSON.stringify({
        wsExists: !!ws,
        ...(ws ? { location: ws.location, rootId: ws.rootId } : {}),
        fsAvailable,
        sourceKind,
        sourceId: source?.id ?? null,
      })}`,
    );
  }, [ws, fsAvailable, source]);

  if (!conversationId) {
    return (
      <EmptyHint
        inline
        icon={<FolderOpen size={26} className="text-muted-foreground/40" />}
        title="尚无工作区"
        hint="发送第一条消息后，这个对话的项目空间就会出现在这里。"
      />
    );
  }

  const handleExport = async () => {
    if (!conversationId || exporting) return;
    setExporting(true);
    try {
      if (fsAvailable) {
        const result = await exportWorkspaceToLocal(conversationId);
        if (result.ok) {
          notifySuccess(
            `已导出 ${result.fileCount} 个文件到「${result.destName}」`,
          );
        } else if (result.reason === "cancelled") {
          /* user dismissed picker */
        } else if (result.reason === "unavailable") {
          await exportWorkspaceZip(conversationId);
        } else {
          notifyActionError("导出到本地失败", new Error(result.message));
        }
      } else {
        await exportWorkspaceZip(conversationId);
      }
    } catch (e) {
      notifyActionError("导出工作区失败", e);
    } finally {
      setExporting(false);
    }
  };

  const emptyTreeHint = fsAvailable
    ? "工作区暂无文件。AI 产物会出现在这里；需要时可用「导出到本地」落到本机目录。"
    : "工作区暂无文件。AI 产物会出现在这里；需要时可导出 ZIP。";

  // D2: shared-space mounts are cloud-execution only (local-bound chats have no
  // cross-runtime dual root).
  const isCloudWorkspace = ws?.location === "cloud";

  return (
    <div className="relative flex h-full flex-col">
      {/* 单行面板头：云端选择器（leading）+ 文件操作 + 快照（trailing）合到 FilesSection
          的工具栏一行（文件操作经其内部 FileTree 的 ref 驱动），不再单独占一行。 */}
      <div className="min-h-0 flex-1">
        <FilesSection
          source={source}
          emptyTreeHint={emptyTreeHint}
          leading={<WorkspaceModeBar conversationId={conversationId} />}
          trailing={
            <>
              <WorkspaceClientTools source={source} />
              {source?.caps.snapshots ? (
                <>
                  <IconButton
                    title={fsAvailable ? "导出到本地" : "导出 ZIP"}
                    disabled={exporting}
                    onClick={() => void handleExport()}
                  >
                    {exporting ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : fsAvailable ? (
                      <FolderDown size={14} />
                    ) : (
                      <Download size={14} />
                    )}
                  </IconButton>
                  <IconButton
                    title="快照"
                    onClick={() => setSnapshotsOpen(true)}
                  >
                    <History size={14} />
                  </IconButton>
                </>
              ) : null}
            </>
          }
        />
      </div>

      {isCloudWorkspace ? (
        <SharedMountsSection conversationId={conversationId} />
      ) : null}

      {/* 快照：从常驻 tab 降级为按需 slide-over（低频 / 恢复型操作）。 */}
      {snapshotsOpen && (
        <div className="absolute inset-0 z-20 flex">
          <Button
            variant="ghost"
            aria-label="关闭快照"
            onClick={() => setSnapshotsOpen(false)}
            className="min-w-0 flex-1 rounded-none bg-overlay/40 p-0"
          />
          <div className="flex w-[85%] max-w-[420px] flex-col border-l border-border bg-card shadow-lg animate-dropdown-in">
            <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border pl-3 pr-1">
              <History size={13} className="shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-xs font-medium">
                快照
              </span>
              <IconButton title="关闭" onClick={() => setSnapshotsOpen(false)}>
                <X size={14} />
              </IconButton>
            </div>
            <div className="min-h-0 flex-1">
              <SnapshotsSection conversationId={conversationId} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
