import {
  MemoryUpdateItemRow,
  formatMemoryTime,
  memoryScopeOverview,
} from "@/components/memory/MemoryUpdateItemRow";
import { Card } from "@/components/ui";
import { countPillMuted, statusCardChrome } from "@/components/ui/tone-presets";
import { getConversations } from "@/hooks/useConversations";
import {
  memoryLeafTabName,
  parseProjectMemoryFolderId,
} from "@/services/sources/memorySource";
import type { MemoryUpdate } from "@/stores/conversation";
import { useConversationStore } from "@/stores/conversation";
import { usePersistentDisclosure } from "@/stores/disclosure";
import { Brain, ChevronDown, ChevronRight, NotebookPen } from "lucide-react";
import { useNavigate } from "react-router-dom";

/**
 * Memory-write notice on the conversation timeline (two-layer memory).
 *
 * - ``episodic``: light tip — session digest was filed for later consolidation.
 * - ``semantic``: expandable diff card — what changed in 偏好 / 画像 / 主题.
 */
export function MemoryUpdateCard({ update }: { update: MemoryUpdate }) {
  const navigate = useNavigate();
  const chrome = statusCardChrome("muted");
  const [open, setOpen] = usePersistentDisclosure(`memory:${update.id}`, false);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const conversationFolderId =
    getConversations().find((c) => c.id === conversationId)?.folderId ?? null;

  const isEpisodic = update.kind === "episodic";
  if (isEpisodic) {
    const tip = (update.summary ?? "").trim();
    if (!tip) return null;
    return (
      <Card
        className={`animate-task-card-enter ${chrome.border} ${chrome.surface}`}
      >
        <div className="flex w-full items-start gap-2 px-3 py-2 text-left">
          <NotebookPen
            size={16}
            className={`mt-0.5 shrink-0 ${chrome.accent}`}
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${chrome.accent}`}>
                已记下本场摘要
              </span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                {formatMemoryTime(update.createdAt)}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
              {tip}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  if (update.items.length === 0 && !(update.summary ?? "").trim()) return null;

  const openLeaf = (target: string, projectId?: string | null) => {
    const folderId = parseProjectMemoryFolderId(target) ?? projectId ?? null;
    navigate("/files", {
      state: {
        openMemoryLeaf: {
          path: target,
          name: memoryLeafTabName(target),
          ...(projectId ? { projectId } : {}),
        },
        ...(folderId ? { focusWsId: `folder:${folderId}` } : {}),
      },
    });
  };

  const hasAnyTarget = update.items.some((it) => it.target);
  const scopeOverview = memoryScopeOverview(update.items);
  const title =
    update.items.length > 0
      ? scopeOverview
        ? `记忆已更新 · ${scopeOverview}`
        : "记忆已更新"
      : (update.summary ?? "记忆已整理");

  // Prefer conversation project; else any project id already on the items (for
  // 「移到全局」 / naming when the card was produced in a project chat).
  const projectFolderId =
    conversationFolderId ||
    update.items.find((it) => it.projectId)?.projectId ||
    null;

  return (
    <Card
      className={`animate-task-card-enter ${chrome.border} ${chrome.surface}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <Brain size={16} className={`shrink-0 ${chrome.accent}`} />
        <span className={`min-w-0 truncate text-xs font-medium ${chrome.accent}`}>
          {title}
        </span>
        {update.items.length > 0 && (
          <span className={countPillMuted}>{update.items.length} 项</span>
        )}
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
          {formatMemoryTime(update.createdAt)}
        </span>
        {update.items.length > 0 ? (
          open ? (
            <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={14}
              className="shrink-0 text-muted-foreground"
            />
          )
        ) : null}
      </button>
      {open && update.items.length > 0 && (
        <div className="px-3 pb-3">
          <ul className="space-y-0.5">
            {update.items.map((item, i) => (
              <MemoryUpdateItemRow
                key={`${item.action}:${item.file}:${item.section}:${i}`}
                item={item}
                onOpenLeaf={openLeaf}
                projectFolderId={projectFolderId}
              />
            ))}
          </ul>
          {!hasAnyTarget && (
            <div className="mt-2 flex justify-end">
              <a
                href="#/files"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                在「AI 记忆」中查看
                <ChevronRight size={13} />
              </a>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
