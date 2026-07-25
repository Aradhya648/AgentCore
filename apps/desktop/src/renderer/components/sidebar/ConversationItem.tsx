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
import {
  SimpleTooltip,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useArchiveConversation,
  useDeleteConversation,
  useDuplicateConversation,
  useRenameConversation,
  useTogglePin,
  useUnarchiveConversation,
} from "@/hooks/useConversations";
import { useFolders } from "@/hooks/useFolders";
import { shouldShowConversationCloudIcon } from "@/lib/conversationWorkspaceMode";
import { notifyError, notifyInfo } from "@/lib/toast";
import {
  type ExportFormat,
  exportConversation,
} from "@/services/conversations";
import {
  type Conversation,
  useConversationGenerating,
  useConversationStore,
} from "@/stores/conversation";
import {
  isAwaitingUserEntry,
  useInteractionStore,
} from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";
import { useShareStore } from "@/stores/share";
import {
  Archive,
  Check,
  Copy,
  Download,
  FileJson,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Share2,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ConversationCloudIcon } from "./ConversationWorkspaceModeIcon";

const PREVIEW_DELAY_MS = 500;
const PREVIEW_MAX_CHARS = 80;
const EMPTY_MESSAGES: { role: "user" | "assistant"; content: string }[] = [];

function timeAgo(date: string | Date): string {
  const ms = Date.now() - new Date(date).getTime();
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const d = Math.floor(hr / 24);
  return `${d} 天前`;
}

function truncatePreview(text: string, max = PREVIEW_MAX_CHARS): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max)}…`;
}

function buildMessagePreview(
  lastMessagePreview: string | null,
  messages: { role: "user" | "assistant"; content: string }[],
): string | null {
  if (lastMessagePreview?.trim()) {
    return truncatePreview(lastMessagePreview);
  }
  if (messages.length === 0) return null;

  let lastUser: (typeof messages)[number] | null = null;
  let lastAssistant: (typeof messages)[number] | null = null;
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (!msg.content.trim()) continue;
    if (msg.role === "assistant" && !lastAssistant) lastAssistant = msg;
    if (msg.role === "user" && !lastUser) lastUser = msg;
    if (lastUser && lastAssistant) break;
  }

  const parts: string[] = [];
  if (lastUser) {
    parts.push(`你: ${truncatePreview(lastUser.content, 40)}`);
  }
  if (lastAssistant) {
    parts.push(`AI: ${truncatePreview(lastAssistant.content, 40)}`);
  }
  if (parts.length > 0) return parts.join(" → ");

  const last = messages[messages.length - 1];
  if (!last.content.trim()) return null;
  const roleLabel = last.role === "user" ? "你" : "AI";
  return `${roleLabel}: ${truncatePreview(last.content)}`;
}

interface Props {
  conversation: Conversation;
  /** When set, row only shows a cloud icon if this chat differs from the group default. */
  groupIsLocal?: boolean;
  /** Extra SurfaceRow classes (e.g. `px-2` to match workspace group headers). */
  className?: string;
}

export function ConversationItem({
  conversation,
  groupIsLocal,
  className,
}: Props) {
  const [hovered, setHovered] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [draft, setDraft] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);
  const skipBlurRef = useRef(false);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const currentId = useConversationStore((s) => s.currentConversationId);
  const cachedMessages = useConversationStore(
    (s) => s.byId[conversation.id]?.messages ?? EMPTY_MESSAGES,
  );
  const switchConversation = useConversationStore((s) => s.switchConversation);
  const dropConversationRuntime = useConversationStore(
    (s) => s.dropConversationRuntime,
  );
  const renameMutation = useRenameConversation();
  const deleteMutation = useDeleteConversation();
  const pinMutation = useTogglePin();
  const duplicateMutation = useDuplicateConversation();
  const archiveMutation = useArchiveConversation();
  const unarchiveMutation = useUnarchiveConversation();
  const folders = useFolders();
  const isGenerating = useConversationGenerating(conversation.id);
  // 「等你」灯（前端UX设计.md §对话列表状态点）：热阻塞交互（审批 / 授权 / 升级拍板，
  // CEO 仲裁除外）+ 任意 kind 的暂停帧（开工确认 / 途中提问 / 计划复核）都算等用户。
  const awaitingInteraction = useInteractionStore((s) =>
    [...s.byId.values()].some(
      (e) => e.conversationId === conversation.id && isAwaitingUserEntry(e),
    ),
  );
  const awaitingResume = usePausedTurnStore((s) =>
    s.pending.some((p) => p.conversationId === conversation.id),
  );
  const navigate = useNavigate();
  const isActive = conversation.id === currentId;
  const currentFolderId = conversation.folderId ?? null;
  const showRowActions = hovered || confirmingDelete || moreOpen;
  const deleteConfirmLabel = currentFolderId
    ? "确认永久删除（项目文件会保留）"
    : "确认永久删除（无法恢复）";

  const status: "running" | "awaiting" | null =
    awaitingInteraction || awaitingResume
      ? "awaiting"
      : isGenerating
        ? "running"
        : null;

  const suppressPreview = moreOpen || confirmingDelete || contextMenuOpen;
  const messagePreview = useMemo(
    () => buildMessagePreview(conversation.lastMessagePreview, cachedMessages),
    [conversation.lastMessagePreview, cachedMessages],
  );
  const showCloudIcon = shouldShowConversationCloudIcon(
    conversation,
    groupIsLocal,
    conversation.folderId
      ? (folders.find((f) => f.id === conversation.folderId) ?? null)
      : null,
  );

  const clearPreviewTimer = useCallback(() => {
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
      previewTimerRef.current = undefined;
    }
  }, []);

  useEffect(() => {
    if (suppressPreview) {
      clearPreviewTimer();
      setPreviewVisible(false);
    }
  }, [suppressPreview, clearPreviewTimer]);

  useEffect(() => () => clearPreviewTimer(), [clearPreviewTimer]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const startEdit = () => {
    setConfirmingDelete(false);
    setDraft(conversation.title);
    setEditing(true);
  };

  const commitEdit = () => {
    setEditing(false);
    const title = draft.trim();
    if (!title || title === conversation.title) return;
    renameMutation.mutate(
      { id: conversation.id, title },
      { onError: (err) => notifyError(err, "重命名失败") },
    );
  };

  const handleDelete = async () => {
    setConfirmingDelete(false);
    const wasActive = conversation.id === currentId;
    try {
      await deleteMutation.mutateAsync(conversation.id);
    } catch (err) {
      notifyError(err, "删除失败");
      return;
    }
    dropConversationRuntime(conversation.id);
    if (wasActive) navigate("/");
  };

  const togglePin = () => {
    pinMutation.mutate(
      { id: conversation.id, pinned: !conversation.pinned },
      { onError: (err) => notifyError(err, "操作失败") },
    );
  };

  const handleArchive = async () => {
    const wasActive = conversation.id === currentId;
    const title = conversation.title;
    try {
      await archiveMutation.mutateAsync(conversation.id);
    } catch (err) {
      notifyError(err, "归档失败");
      return;
    }
    dropConversationRuntime(conversation.id);
    if (wasActive) navigate("/");
    notifyInfo("已归档", {
      description: title,
      duration: 5000,
      action: {
        label: "撤销",
        onClick: () => {
          unarchiveMutation.mutate(conversation.id, {
            onError: (err) => notifyError(err, "取消归档失败"),
          });
        },
      },
    });
  };

  const handleDuplicate = () => {
    setMoreOpen(false);
    duplicateMutation.mutate(conversation.id, {
      onSuccess: (conv) => {
        switchConversation(conv.id);
        navigate(`/conversations/${conv.id}`);
      },
      onError: (err) => notifyError(err, "克隆失败"),
    });
  };

  const handleExport = async (format: ExportFormat) => {
    try {
      await exportConversation(conversation.id, format);
    } catch (err) {
      notifyError(err, "导出失败");
    }
  };

  const requestPermanentDelete = () => {
    setMoreOpen(false);
    setConfirmingDelete(true);
  };

  const openConversation = () => {
    switchConversation(conversation.id);
    navigate(`/conversations/${conversation.id}`);
  };

  const rowActionClass =
    "size-6 text-sidebar-foreground/40 hover:text-sidebar-foreground";

  if (editing) {
    return (
      <div className="flex h-9 w-full items-center rounded-lg bg-sidebar-accent px-2">
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
          className="h-7 min-w-0 flex-1 bg-transparent px-1 text-sm text-sidebar-accent-foreground focus:outline-none"
        />
      </div>
    );
  }

  return (
    <ContextMenu
      onOpenChange={(open) => {
        setContextMenuOpen(open);
        if (open) setConfirmingDelete(false);
      }}
    >
      <Tooltip
        open={previewVisible}
        onOpenChange={(open) => {
          if (!open) setPreviewVisible(false);
        }}
      >
        <TooltipTrigger asChild>
          <ContextMenuTrigger asChild>
            <SurfaceRow
              variant="sidebar"
              active={isActive}
              className={className}
              onMouseEnter={() => {
                setHovered(true);
                if (!suppressPreview) {
                  clearPreviewTimer();
                  previewTimerRef.current = setTimeout(
                    () => setPreviewVisible(true),
                    PREVIEW_DELAY_MS,
                  );
                }
              }}
              onMouseLeave={() => {
                setHovered(false);
                clearPreviewTimer();
                setPreviewVisible(false);
                if (!moreOpen) setConfirmingDelete(false);
              }}
            >
              {/* biome-ignore lint/a11y/useSemanticElements: 行内另有 DropdownMenuTrigger 的真 <button>，此可点击区不可套 <button>。 */}
              <div
                role="button"
                tabIndex={0}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                onClick={openConversation}
                onDoubleClick={(e) => {
                  e.preventDefault();
                  startEdit();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openConversation();
                  }
                }}
              >
                {/* Always reserve the group-header icon slot (size-3.5) so
                    titles share one column whether the row shows status, cloud,
                    or neither. */}
                <span className="inline-flex size-3.5 shrink-0 items-center justify-center">
                  {status ? (
                    <SimpleTooltip
                      label={status === "running" ? "执行中" : "等你决策"}
                    >
                      <span
                        aria-label={
                          status === "running" ? "执行中" : "等你决策"
                        }
                        className={`size-1.5 rounded-full ${
                          status === "running"
                            ? "animate-pulse bg-primary"
                            : "bg-primary ring-2 ring-primary/25"
                        }`}
                      />
                    </SimpleTooltip>
                  ) : (
                    showCloudIcon && <ConversationCloudIcon />
                  )}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {conversation.title}
                </span>
              </div>
              {confirmingDelete ? (
                <span className="flex shrink-0 items-center gap-0.5">
                  <SimpleTooltip label={deleteConfirmLabel}>
                    <IconButton
                      tone="sidebar"
                      aria-label={deleteConfirmLabel}
                      className="size-6 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDelete();
                      }}
                    >
                      <Check size={13} />
                    </IconButton>
                  </SimpleTooltip>
                  <SimpleTooltip label="取消">
                    <IconButton
                      tone="sidebar"
                      aria-label="取消"
                      className={rowActionClass}
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmingDelete(false);
                      }}
                    >
                      <X size={13} />
                    </IconButton>
                  </SimpleTooltip>
                </span>
              ) : showRowActions ? (
                <span className="flex shrink-0 items-center gap-0.5">
                  <SimpleTooltip label="重命名">
                    <IconButton
                      tone="sidebar"
                      aria-label="重命名"
                      className={rowActionClass}
                      onClick={(e) => {
                        e.stopPropagation();
                        startEdit();
                      }}
                    >
                      <Pencil size={13} />
                    </IconButton>
                  </SimpleTooltip>
                  <SimpleTooltip label="归档">
                    <IconButton
                      tone="sidebar"
                      aria-label="归档"
                      className={rowActionClass}
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleArchive();
                      }}
                    >
                      <Archive size={13} />
                    </IconButton>
                  </SimpleTooltip>
                  <DropdownMenu open={moreOpen} onOpenChange={setMoreOpen}>
                    <DropdownMenuTrigger asChild>
                      <IconButton
                        tone="sidebar"
                        aria-label="更多操作"
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
                      <DropdownMenuItem onSelect={() => togglePin()}>
                        {conversation.pinned ? (
                          <PinOff size={14} className="shrink-0" />
                        ) : (
                          <Pin size={14} className="shrink-0" />
                        )}
                        <span className="flex-1 truncate">
                          {conversation.pinned ? "取消置顶" : "置顶"}
                        </span>
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={handleDuplicate}>
                        <Copy size={14} className="shrink-0" />
                        <span className="flex-1 truncate">克隆对话</span>
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() =>
                          useShareStore.getState().open(conversation.id)
                        }
                      >
                        <Share2 size={14} className="shrink-0" />
                        <span className="flex-1 truncate">分享…</span>
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => void handleExport("md")}
                      >
                        <Download size={14} className="shrink-0" />
                        <span className="flex-1 truncate">导出 Markdown</span>
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => void handleExport("json")}
                      >
                        <FileJson size={14} className="shrink-0" />
                        <span className="flex-1 truncate">导出 JSON</span>
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        variant="danger"
                        onSelect={requestPermanentDelete}
                      >
                        <Trash2 size={14} className="shrink-0" />
                        <span className="flex-1 truncate">永久删除</span>
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </span>
              ) : conversation.pinned ? (
                <Pin
                  size={12}
                  className="shrink-0 text-sidebar-foreground/40"
                  aria-label="已置顶"
                />
              ) : null}
            </SurfaceRow>
          </ContextMenuTrigger>
        </TooltipTrigger>
        <TooltipContent
          side="right"
          align="start"
          className="max-w-sm px-3 py-2"
        >
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-semibold">{conversation.title}</p>
            <p className="text-xs text-muted-foreground">
              最后更新: {timeAgo(conversation.updatedAt)}
            </p>
            {messagePreview && (
              <>
                <div className="border-t border-border" />
                <p className="text-xs leading-relaxed">{messagePreview}</p>
              </>
            )}
          </div>
        </TooltipContent>
      </Tooltip>

      <ContextMenuContent className="min-w-52">
        <ContextMenuItem onSelect={() => startEdit()}>
          <Pencil size={14} className="shrink-0" />
          <span className="flex-1 truncate">重命名</span>
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => void handleArchive()}>
          <Archive size={14} className="shrink-0" />
          <span className="flex-1 truncate">归档</span>
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={() => togglePin()}>
          {conversation.pinned ? (
            <PinOff size={14} className="shrink-0" />
          ) : (
            <Pin size={14} className="shrink-0" />
          )}
          <span className="flex-1 truncate">
            {conversation.pinned ? "取消置顶" : "置顶"}
          </span>
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={handleDuplicate}>
          <Copy size={14} className="shrink-0" />
          <span className="flex-1 truncate">克隆对话</span>
        </ContextMenuItem>
        <ContextMenuItem
          onSelect={() => useShareStore.getState().open(conversation.id)}
        >
          <Share2 size={14} className="shrink-0" />
          <span className="flex-1 truncate">分享…</span>
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => void handleExport("md")}>
          <Download size={14} className="shrink-0" />
          <span className="flex-1 truncate">导出 Markdown</span>
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => void handleExport("json")}>
          <FileJson size={14} className="shrink-0" />
          <span className="flex-1 truncate">导出 JSON</span>
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem variant="danger" onSelect={requestPermanentDelete}>
          <Trash2 size={14} className="shrink-0" />
          <span className="flex-1 truncate">永久删除</span>
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
