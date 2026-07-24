import { FileTree, type FileTreeHandle } from "@/components/files/FileTree";
import { IconButton } from "@/components/files/parts";
import { CreateSharedSpaceDialog } from "@/components/files/sharedSpaces/CreateSharedSpaceDialog";
import { SharedSpaceEventsDialog } from "@/components/files/sharedSpaces/SharedSpaceEventsDialog";
import { SharedSpaceMembersDialog } from "@/components/files/sharedSpaces/SharedSpaceMembersDialog";
import { Button } from "@/components/ui";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  useDeleteSharedSpace,
  useRemoveOrLeaveSharedMember,
  useRenameSharedSpace,
} from "@/hooks/useSharedSpaces";
import type { FileSource } from "@/lib/fileSource";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  type SharedSpaceSummary,
  canWriteSharedSpace,
  sharedSpaceRoleLabel,
} from "@/services/sharedSpaces";
import { useAuthStore } from "@/stores/auth";
import {
  Check,
  ChevronDown,
  ChevronRight,
  FilePlus,
  FolderOpen,
  FolderPlus,
  History,
  Pencil,
  Trash2,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * One shared-space root in the files rail — same collapsible section chrome as
 * {@link WorkspaceSection}, plus members / events / leave·delete.
 */
export function SharedSpaceSection({
  space,
  source,
  activePath,
  expanded,
  onToggle,
  onOpenFile,
  flashing,
}: {
  space: SharedSpaceSummary;
  source: FileSource | null;
  activePath: string | null;
  expanded: boolean;
  onToggle: () => void;
  onOpenFile: (path: string, name: string) => void;
  flashing: boolean;
}) {
  const meId = useAuthStore((s) => s.user?.id ?? null);
  const canWrite = canWriteSharedSpace(space.my_role);
  const isOwner = space.my_role === "owner";

  const rootRef = useRef<HTMLDivElement>(null);
  const treeRef = useRef<FileTreeHandle>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const skipBlurRef = useRef(false);
  const [pendingAction, setPendingAction] = useState<
    "file" | "dir" | "upload" | null
  >(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(space.name);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [membersOpen, setMembersOpen] = useState(false);
  const [eventsOpen, setEventsOpen] = useState(false);

  const rename = useRenameSharedSpace();
  const del = useDeleteSharedSpace();
  const leave = useRemoveOrLeaveSharedMember();

  useEffect(() => {
    if (flashing) rootRef.current?.scrollIntoView({ block: "nearest" });
  }, [flashing]);

  useEffect(() => {
    if (!expanded || !pendingAction || !canWrite) return;
    if (pendingAction === "upload") treeRef.current?.triggerUpload();
    else treeRef.current?.startCreate(pendingAction);
    setPendingAction(null);
  }, [expanded, pendingAction, canWrite]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  useEffect(() => {
    if (!editing) setDraft(space.name);
  }, [space.name, editing]);

  const requestTreeAction = (action: "file" | "dir" | "upload") => {
    if (!canWrite) return;
    if (expanded) {
      if (action === "upload") treeRef.current?.triggerUpload();
      else treeRef.current?.startCreate(action);
    } else {
      setPendingAction(action);
      onToggle();
    }
  };

  const startEdit = () => {
    if (!isOwner) return;
    setConfirmingDelete(false);
    setDraft(space.name);
    setEditing(true);
  };

  const commitEdit = () => {
    setEditing(false);
    if (!isOwner) return;
    const name = draft.trim();
    if (!name || name === space.name) return;
    rename.mutate(
      { spaceId: space.id, name },
      { onError: (err) => notifyError(err, "重命名失败") },
    );
  };

  const handleDeleteOrLeave = () => {
    if (isOwner) {
      if (
        !window.confirm(
          `确定删除共享空间「${space.name}」？所有成员将失去访问，文件不可恢复。`,
        )
      ) {
        return;
      }
      del.mutate(space.id, {
        onSuccess: () => notifySuccess("已删除共享空间"),
        onError: (err) => notifyError(err, "删除失败"),
      });
      return;
    }
    if (!meId) return;
    if (!window.confirm(`确定退出共享空间「${space.name}」？`)) return;
    leave.mutate(
      { spaceId: space.id, memberUserId: meId },
      {
        onSuccess: () => notifySuccess("已退出共享空间"),
        onError: (err) => notifyError(err, "退出失败"),
      },
    );
  };

  const header = editing ? (
    <div
      className={cn(
        "flex h-9 items-center rounded-lg px-2",
        flashing && "ring-2 ring-inset ring-primary",
      )}
    >
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            inputRef.current?.blur();
          } else if (e.key === "Escape") {
            e.preventDefault();
            skipBlurRef.current = true;
            setEditing(false);
          }
        }}
        onBlur={() => {
          if (skipBlurRef.current) {
            skipBlurRef.current = false;
            return;
          }
          commitEdit();
        }}
        className="h-7 min-w-0 flex-1 bg-transparent px-1 text-sm focus:outline-none"
        aria-label="重命名共享空间"
      />
    </div>
  ) : (
    <div
      className={cn(
        "group flex items-center rounded-lg pr-1 text-sm",
        flashing && "ring-2 ring-inset ring-primary",
      )}
    >
      <Button
        variant="ghost"
        onClick={onToggle}
        aria-expanded={expanded}
        className="h-auto min-h-9 min-w-0 flex-1 justify-start gap-1.5 overflow-hidden rounded-none py-1.5 pl-2 pr-0 text-left text-sm font-medium"
      >
        {expanded ? (
          <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-muted-foreground" />
        )}
        <FolderOpen size={14} className="shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-medium">
          {space.name}
        </span>
      </Button>
      {confirmingDelete ? (
        <div className="flex shrink-0 items-center">
          <IconButton
            title={isOwner ? "确认删除空间" : "确认退出"}
            onClick={() => {
              setConfirmingDelete(false);
              handleDeleteOrLeave();
            }}
          >
            <Check size={14} className="text-destructive" />
          </IconButton>
          <IconButton title="取消" onClick={() => setConfirmingDelete(false)}>
            <X size={14} />
          </IconButton>
        </div>
      ) : (
        canWrite &&
        source && (
          <div className="hidden shrink-0 items-center group-hover:flex">
            <IconButton
              title="新建文件"
              onClick={() => requestTreeAction("file")}
            >
              <FilePlus size={14} />
            </IconButton>
            <IconButton
              title="新建文件夹"
              onClick={() => requestTreeAction("dir")}
            >
              <FolderPlus size={14} />
            </IconButton>
          </div>
        )
      )}
      <span className="flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
        <Users size={12} />
        {sharedSpaceRoleLabel(space.my_role)}
      </span>
    </div>
  );

  const tree = source ? (
    <FileTree
      ref={treeRef}
      source={source}
      chrome={false}
      indent={14}
      activePath={activePath}
      onOpenFile={onOpenFile}
      emptyText={
        canWrite
          ? "还没有文件——把产出放进这里，成员就能看到"
          : "还没有文件（只读）"
      }
    />
  ) : (
    <div className="py-1 pl-7 text-xs text-muted-foreground/70">
      无法打开此共享空间，文件源暂不可用。
    </div>
  );

  return (
    <div ref={rootRef}>
      {editing ? (
        header
      ) : (
        <ContextMenu
          onOpenChange={(openMenu) => {
            if (openMenu) setConfirmingDelete(false);
          }}
        >
          <ContextMenuTrigger asChild>{header}</ContextMenuTrigger>
          <ContextMenuContent className="min-w-44">
            {canWrite && source && (
              <>
                <ContextMenuItem onSelect={() => requestTreeAction("file")}>
                  <FilePlus size={14} className="shrink-0" />
                  <span className="flex-1 truncate">新建文件</span>
                </ContextMenuItem>
                <ContextMenuItem onSelect={() => requestTreeAction("dir")}>
                  <FolderPlus size={14} className="shrink-0" />
                  <span className="flex-1 truncate">新建文件夹</span>
                </ContextMenuItem>
                {source.caps.transfer && (
                  <ContextMenuItem onSelect={() => requestTreeAction("upload")}>
                    <Upload size={14} className="shrink-0" />
                    <span className="flex-1 truncate">上传文件</span>
                  </ContextMenuItem>
                )}
                <ContextMenuSeparator />
              </>
            )}
            <ContextMenuItem onSelect={() => setMembersOpen(true)}>
              <Users size={14} className="shrink-0" />
              <span className="flex-1 truncate">成员管理</span>
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => setEventsOpen(true)}>
              <History size={14} className="shrink-0" />
              <span className="flex-1 truncate">变更记录</span>
            </ContextMenuItem>
            {isOwner && (
              <ContextMenuItem onSelect={startEdit}>
                <Pencil size={14} className="shrink-0" />
                <span className="flex-1 truncate">重命名</span>
              </ContextMenuItem>
            )}
            <ContextMenuSeparator />
            <ContextMenuItem
              variant="danger"
              onSelect={() => setConfirmingDelete(true)}
            >
              <Trash2 size={14} className="shrink-0" />
              <span className="flex-1 truncate">
                {isOwner ? "删除空间…" : "退出空间…"}
              </span>
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
      )}
      {expanded && tree}
      <SharedSpaceMembersDialog
        open={membersOpen}
        onClose={() => setMembersOpen(false)}
        spaceId={space.id}
        spaceName={space.name}
        myRole={space.my_role}
      />
      <SharedSpaceEventsDialog
        open={eventsOpen}
        onClose={() => setEventsOpen(false)}
        spaceId={space.id}
        spaceName={space.name}
      />
    </div>
  );
}

/** Section header row with「新建」for the shared-spaces group. */
export function SharedSpacesRailHeader({
  onCreated,
}: {
  onCreated?: (spaceId: string) => void;
}) {
  const [createOpen, setCreateOpen] = useState(false);
  return (
    <>
      <div className="flex items-center gap-1 px-2 pb-0.5 pt-2">
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-muted-foreground">
          共享空间
        </span>
        <IconButton title="新建共享空间" onClick={() => setCreateOpen(true)}>
          <FolderPlus size={13} />
        </IconButton>
      </div>
      <CreateSharedSpaceDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={onCreated}
      />
    </>
  );
}
