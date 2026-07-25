import {
  DeleteFolderDialog,
  archiveConversationsBeforeDelete,
} from "@/components/folders/DeleteFolderDialog";
import { IconButton, SurfaceRow } from "@/components/ui";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useArchiveConversation } from "@/hooks/useConversations";
import { useDeleteFolder, usePermanentDeleteFolder } from "@/hooks/useFolders";
import { deriveGroupWorkspaceIsLocal } from "@/lib/conversationWorkspaceMode";
import { startNewConversation } from "@/lib/newConversation";
import { notifyError, notifyInfo } from "@/lib/toast";
import type { FolderMeta } from "@/services/folders";
import type { Conversation } from "@/stores/conversation";
import { useConversationStore } from "@/stores/conversation";
import {
  Archive,
  ChevronRight,
  FolderOpen,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { GroupWorkspaceModeIcon } from "./ConversationWorkspaceModeIcon";

interface Props {
  folder: FolderMeta;
  /** Every live conversation in this folder (not just the sidebar Top-N slice). */
  convs: Conversation[];
  expanded: boolean;
  onToggleExpanded: () => void;
}

/**
 * Sidebar「项目」group header: left icon slot (cloud/local; hover overlays
 * chevron for collapse) + name + hover「+」new chat in project +「⋯».
 * Right-click and hover「⋯」share the same menu;「归档全部对话」maps to
 * batch conversation archive (no `Folder.archived`).
 */
export function WorkspaceGroupHeader({
  folder,
  convs,
  expanded,
  onToggleExpanded,
}: Props) {
  const [moreOpen, setMoreOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const navigate = useNavigate();
  const archiveMutation = useArchiveConversation();
  const deleteFolderMutation = useDeleteFolder();
  const permanentDeleteMutation = usePermanentDeleteFolder();
  const currentId = useConversationStore((s) => s.currentConversationId);
  const dropConversationRuntime = useConversationStore(
    (s) => s.dropConversationRuntime,
  );

  const liveConvCount = convs.length;
  const groupIsLocal = useMemo(
    () => deriveGroupWorkspaceIsLocal(folder),
    [folder],
  );

  const viewAllConversations = () => {
    navigate("/conversations", { state: { focusFolderId: folder.id } });
  };

  const browseFiles = () => {
    navigate("/files", { state: { focusWsId: `folder:${folder.id}` } });
  };

  const newChatInProject = () => {
    setMoreOpen(false);
    startNewConversation(navigate, folder.id);
  };

  const handleArchiveAll = async () => {
    setMoreOpen(false);
    if (convs.length === 0) return;
    const ok = await archiveConversationsBeforeDelete(convs, {
      archive: (id) => archiveMutation.mutateAsync(id),
      dropRuntime: dropConversationRuntime,
      currentId,
      onLeaveActive: () => navigate("/"),
    });
    if (!ok) {
      notifyError("批量归档失败");
      return;
    }
    notifyInfo(`已归档 ${convs.length} 条对话`, {
      description: folder.name,
    });
  };

  const confirmDeleteFolder = async () => {
    if (convs.length > 0) {
      const ok = await archiveConversationsBeforeDelete(convs, {
        archive: (id) => archiveMutation.mutateAsync(id),
        dropRuntime: dropConversationRuntime,
        currentId,
        onLeaveActive: () => navigate("/"),
      });
      if (!ok) {
        notifyError("归档失败，项目未删除");
        return;
      }
    }
    deleteFolderMutation.mutate(folder.id, {
      onSuccess: () => setDeleteOpen(false),
      onError: (err) => notifyError(err, "删除项目失败"),
    });
  };

  const confirmPermanentDelete = () => {
    for (const { id } of convs) {
      dropConversationRuntime(id);
      if (id === currentId) navigate("/");
    }
    permanentDeleteMutation.mutate(folder.id, {
      onSuccess: () => setDeleteOpen(false),
      onError: (err) => notifyError(err, "彻底删除失败"),
    });
  };

  const archiveLabel =
    liveConvCount > 0 ? `归档全部对话 (${liveConvCount})` : "归档全部对话";

  const menuItems = (
    <>
      <ContextMenuItem onSelect={newChatInProject}>
        <Plus size={14} className="shrink-0" />
        <span className="flex-1 truncate">新建对话</span>
      </ContextMenuItem>
      <ContextMenuItem onSelect={viewAllConversations}>
        <MessageSquare size={14} className="shrink-0" />
        <span className="flex-1 truncate">查看全部对话</span>
      </ContextMenuItem>
      <ContextMenuItem onSelect={browseFiles}>
        <FolderOpen size={14} className="shrink-0" />
        <span className="flex-1 truncate">浏览文件</span>
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem
        disabled={liveConvCount === 0}
        onSelect={() => void handleArchiveAll()}
      >
        <Archive size={14} className="shrink-0" />
        <span className="flex-1 truncate">{archiveLabel}</span>
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem variant="danger" onSelect={() => setDeleteOpen(true)}>
        <Trash2 size={14} className="shrink-0" />
        <span className="flex-1 truncate">删除项目…</span>
      </ContextMenuItem>
    </>
  );

  const dropdownItems = (
    <>
      <DropdownMenuItem onSelect={newChatInProject}>
        <Plus size={14} className="shrink-0" />
        <span className="flex-1 truncate">新建对话</span>
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={viewAllConversations}>
        <MessageSquare size={14} className="shrink-0" />
        <span className="flex-1 truncate">查看全部对话</span>
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={browseFiles}>
        <FolderOpen size={14} className="shrink-0" />
        <span className="flex-1 truncate">浏览文件</span>
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        disabled={liveConvCount === 0}
        onSelect={() => void handleArchiveAll()}
      >
        <Archive size={14} className="shrink-0" />
        <span className="flex-1 truncate">{archiveLabel}</span>
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem variant="danger" onSelect={() => setDeleteOpen(true)}>
        <Trash2 size={14} className="shrink-0" />
        <span className="flex-1 truncate">删除项目…</span>
      </DropdownMenuItem>
    </>
  );

  const rowActionClass =
    "size-6 text-sidebar-foreground/40 hover:text-sidebar-foreground";

  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <SurfaceRow
            variant="sidebar"
            className="group h-9 px-2 text-sidebar-foreground/70 hover:text-sidebar-foreground"
          >
            {/* biome-ignore lint/a11y/useSemanticElements: 行内嵌 DropdownMenuTrigger 的真 <button>，此可点击区不可套 <button>。 */}
            <div
              role="button"
              tabIndex={0}
              aria-expanded={expanded}
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
              onClick={onToggleExpanded}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onToggleExpanded();
                }
              }}
            >
              <span className="relative inline-flex size-3.5 shrink-0 items-center justify-center">
                <span className="absolute inset-0 flex items-center justify-center opacity-100 transition-opacity group-hover:pointer-events-none group-hover:opacity-0">
                  <GroupWorkspaceModeIcon isLocal={groupIsLocal} />
                </span>
                <ChevronRight
                  size={14}
                  aria-hidden
                  className={`absolute text-sidebar-foreground/40 opacity-0 transition-[opacity,transform] group-hover:opacity-100 ${
                    expanded ? "rotate-90" : ""
                  }`}
                />
              </span>
              <span className="min-w-0 flex-1 truncate">{folder.name}</span>
            </div>
            <span
              className={`flex shrink-0 items-center gap-0.5 ${
                moreOpen
                  ? "opacity-100"
                  : "opacity-0 transition-opacity group-hover:opacity-100"
              }`}
            >
              <DropdownMenu open={moreOpen} onOpenChange={setMoreOpen}>
                <DropdownMenuTrigger asChild>
                  <IconButton
                    tone="sidebar"
                    aria-label="项目操作"
                    title="更多"
                    className={rowActionClass}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <MoreHorizontal size={13} />
                  </IconButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="min-w-52"
                  onClick={(e) => e.stopPropagation()}
                >
                  {dropdownItems}
                </DropdownMenuContent>
              </DropdownMenu>
              <IconButton
                tone="sidebar"
                aria-label="在此项目新建对话"
                title="在此项目新建对话"
                className={rowActionClass}
                onClick={(e) => {
                  e.stopPropagation();
                  newChatInProject();
                }}
              >
                <Plus size={13} />
              </IconButton>
            </span>
          </SurfaceRow>
        </ContextMenuTrigger>
        <ContextMenuContent className="min-w-52">
          {menuItems}
        </ContextMenuContent>
      </ContextMenu>
      <DeleteFolderDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        name={folder.name}
        liveConvCount={liveConvCount}
        isLocal={groupIsLocal}
        onConfirm={() => void confirmDeleteFolder()}
        onPermanentConfirm={confirmPermanentDelete}
      />
    </>
  );
}
