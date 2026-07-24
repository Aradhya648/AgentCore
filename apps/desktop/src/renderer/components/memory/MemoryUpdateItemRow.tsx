import { countPillMuted, statusPillInline } from "@/components/ui/tone-presets";
import type { MemoryUpdateItem } from "@/stores/conversation";
import { ChevronRight } from "lucide-react";

/**
 * One applied memory change (新增/更新/移除 + 目标叶子 + 正文), shared by the in-conversation
 * 「记忆已更新」card ({@link MemoryUpdateCard}) and the「AI 记忆」editor's跨对话「最近更新」feed
 * ({@link MemoryUpdatesView}) — one source of truth for how a change reads, so the two
 * surfaces never drift (Agent记忆与知识系统 §1.6).
 *
 * A row with a `target` is a button that deep-links to that exact memory leaf (the caller
 * decides HOW to open it — navigate to /files from the conversation, or open a tab directly
 * inside the editor); rows without a resolvable `target` render as plain text.
 */

const ACTION_META: Record<
  string,
  { label: string; tone: "success" | "primary" | "muted" }
> = {
  add: { label: "新增", tone: "success" },
  update: { label: "更新", tone: "primary" },
  remove: { label: "移除", tone: "muted" },
};

function scopeLabel(scope: string): string {
  return scope === "project" ? "本项目" : "全局";
}

export function MemoryUpdateItemRow({
  item,
  onOpenLeaf,
}: {
  item: MemoryUpdateItem;
  onOpenLeaf: (target: string, projectId?: string | null) => void;
}) {
  const meta = ACTION_META[item.action] ?? {
    label: item.action,
    tone: "muted" as const,
  };
  const leafLabel = item.section ? `${item.file} · ${item.section}` : item.file;
  // A remove carries the text that was dropped — strike it through so the row reads
  // as a deletion rather than a new bullet.
  const removed = item.action === "remove";

  const body = (
    <>
      <span className={`shrink-0 ${statusPillInline[meta.tone]}`}>
        {meta.label}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="truncate">{leafLabel}</span>
          <span className={countPillMuted}>{scopeLabel(item.scope)}</span>
        </div>
        {item.content && (
          <p
            className={`mt-0.5 whitespace-pre-wrap break-words text-sm ${
              removed ? "text-muted-foreground line-through" : "text-foreground"
            }`}
          >
            {item.content}
          </p>
        )}
      </div>
    </>
  );

  // Rows with a `target` deep-link to that leaf; others stay plain (no resolvable path).
  if (item.target) {
    return (
      <li>
        <button
          type="button"
          onClick={() => onOpenLeaf(item.target, item.projectId)}
          title={`在「AI 记忆」中打开${item.file}`}
          className="group flex w-full items-start gap-2 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-accent/50"
        >
          {body}
          <ChevronRight
            size={14}
            className="mt-0.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
          />
        </button>
      </li>
    );
  }

  return <li className="flex items-start gap-2 px-1.5 py-1">{body}</li>;
}

/** Timestamp label shared by the memory card + feed (MM-DD HH:mm). */
export function formatMemoryTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}`;
}
