import { countPillMuted, statusPillInline } from "@/components/ui/tone-presets";
import { getFolders } from "@/hooks/useFolders";
import { notifyActionError, notifyInfo } from "@/lib/toast";
import { ApiError } from "@/services/api";
import {
  type MemoryMoveDirection,
  type MemoryMoveKind,
  moveMemoryBullet,
} from "@/services/memory";
import type { MemoryUpdateItem } from "@/stores/conversation";
import { ChevronRight, Loader2 } from "lucide-react";
import { useState } from "react";

/**
 * One applied memory change (新增/更新/移除 + 目标叶子 + 正文), shared by the in-conversation
 * 「记忆已更新」card ({@link MemoryUpdateCard}) and the「AI 记忆」editor's跨对话「最近更新」feed
 * ({@link MemoryUpdatesView}) — one source of truth for how a change reads, so the two
 * surfaces never drift (Agent记忆与知识系统 §1.6).
 *
 * A row with a `target` is a button that deep-links to that exact memory leaf (the caller
 * decides HOW to open it — navigate to /files from the conversation, or open a tab directly
 * inside the editor); rows without a resolvable `target` render as plain text.
 *
 * P2-a: project-scope pill shows `本项目 · {名}` (falls back to「本项目」when the folder
 * name is unknown). P2-b: optional「移到本项目 / 移到全局」on add/update rows when a
 * current project folder is known and the section allows the move.
 */

const ACTION_META: Record<
  string,
  { label: string; tone: "success" | "primary" | "muted" }
> = {
  add: { label: "新增", tone: "success" },
  update: { label: "更新", tone: "primary" },
  remove: { label: "移除", tone: "muted" },
};

/** Resolve a folder id to its display name from the cached folder list. */
export function resolveProjectName(
  projectId: string | null | undefined,
): string | null {
  if (!projectId) return null;
  return getFolders().find((f) => f.id === projectId)?.name ?? null;
}

/** Scope pill label: `全局` / `本项目 · {名}` / `本项目` (name resolve failure). */
export function memoryScopePillLabel(
  scope: string,
  projectId?: string | null,
): string {
  if (scope !== "project") return "全局";
  const name = resolveProjectName(projectId);
  return name ? `本项目 · ${name}` : "本项目";
}

/**
 * Compact scope overview for a card title (e.g. `全局 + 本项目 · Foo`). Empty when
 * there are no items.
 */
export function memoryScopeOverview(
  items: ReadonlyArray<{ scope: string; projectId?: string | null }>,
): string {
  if (items.length === 0) return "";
  const parts: string[] = [];
  if (items.some((it) => it.scope !== "project")) parts.push("全局");
  const seen = new Set<string>();
  for (const it of items) {
    if (it.scope !== "project") continue;
    const key = it.projectId ?? "";
    if (seen.has(key)) continue;
    seen.add(key);
    parts.push(memoryScopePillLabel("project", it.projectId));
  }
  return parts.join(" + ");
}

function moveKindFromItem(item: MemoryUpdateItem): {
  kind: MemoryMoveKind;
  topicSlug: string | null;
} {
  if (item.file === "偏好") return { kind: "preferences", topicSlug: null };
  if (item.file.startsWith("主题·")) {
    return {
      kind: "topic",
      topicSlug: item.file.slice("主题·".length) || null,
    };
  }
  const m = /\/topics\/(.+)$/.exec(item.target ?? "");
  if (m) return { kind: "topic", topicSlug: m[1] };
  return { kind: "profile", topicSlug: null };
}

/** Whether this row may offer a move in ``direction`` (section invariants + content). */
export function canMoveMemoryItem(
  item: MemoryUpdateItem,
  direction: MemoryMoveDirection,
  projectFolderId: string | null | undefined,
): boolean {
  if (item.action === "remove") return false;
  if (!(item.content ?? "").trim()) return false;
  if (!projectFolderId) return false;
  if (
    item.file === "偏好" ||
    item.section === "沟通偏好" ||
    item.section === "工作习惯"
  ) {
    return false;
  }
  if (direction === "to_project") {
    if (item.scope === "project") return false;
    if (item.section === "纠正记录") return false;
    return true;
  }
  if (item.scope !== "project") return false;
  if (item.section === "项目约束") return false;
  return true;
}

export function MemoryUpdateItemRow({
  item,
  onOpenLeaf,
  projectFolderId,
  onMoved,
}: {
  item: MemoryUpdateItem;
  onOpenLeaf: (target: string, projectId?: string | null) => void;
  /** Current project folder — enables「移到本项目」for global rows. */
  projectFolderId?: string | null;
  /** Fired after a successful move (feed may refetch). */
  onMoved?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const meta = ACTION_META[item.action] ?? {
    label: item.action,
    tone: "muted" as const,
  };
  const leafLabel = item.section ? `${item.file} · ${item.section}` : item.file;
  const removed = item.action === "remove";
  const folderId = projectFolderId || item.projectId || null;
  const showToProject = canMoveMemoryItem(item, "to_project", folderId);
  const showToGlobal = canMoveMemoryItem(item, "to_global", folderId);

  const runMove = async (direction: MemoryMoveDirection) => {
    if (!folderId || busy) return;
    setBusy(true);
    try {
      const { kind, topicSlug } = moveKindFromItem(item);
      const result = await moveMemoryBullet({
        content: item.content,
        section: item.section || (kind === "topic" ? "要点" : ""),
        folderId,
        direction,
        kind,
        topicSlug,
      });
      if (result.conflict) {
        notifyInfo("记忆刚被更新，请刷新后再试搬层");
        return;
      }
      notifyInfo(direction === "to_project" ? "已移到本项目" : "已移到全局");
      onMoved?.();
    } catch (e) {
      notifyActionError(
        "搬层失败",
        e instanceof ApiError ? (e.serverMessage ?? e.message) : e,
      );
    } finally {
      setBusy(false);
    }
  };

  const moveControls =
    showToProject || showToGlobal ? (
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {showToProject && (
          <button
            type="button"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              void runMove("to_project");
            }}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
          >
            移到本项目
          </button>
        )}
        {showToGlobal && (
          <button
            type="button"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              void runMove("to_global");
            }}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
          >
            移到全局
          </button>
        )}
        {busy && (
          <Loader2 size={12} className="animate-spin text-muted-foreground" />
        )}
      </div>
    ) : null;

  const metaBlock = (
    <>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="truncate">{leafLabel}</span>
        <span className={countPillMuted}>
          {memoryScopePillLabel(item.scope, item.projectId)}
        </span>
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
    </>
  );

  if (item.target) {
    return (
      <li className="rounded-lg px-1.5 py-1 hover:bg-accent/50">
        <button
          type="button"
          onClick={() => onOpenLeaf(item.target, item.projectId)}
          title={`在「AI 记忆」中打开${item.file}`}
          className="group flex w-full items-start gap-2 text-left"
        >
          <span className={`shrink-0 ${statusPillInline[meta.tone]}`}>
            {meta.label}
          </span>
          <div className="min-w-0 flex-1">{metaBlock}</div>
          <ChevronRight
            size={14}
            className="mt-0.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
          />
        </button>
        {moveControls ? <div className="pl-14">{moveControls}</div> : null}
      </li>
    );
  }

  return (
    <li className="px-1.5 py-1">
      <div className="flex items-start gap-2">
        <span className={`shrink-0 ${statusPillInline[meta.tone]}`}>
          {meta.label}
        </span>
        <div className="min-w-0 flex-1">
          {metaBlock}
          {moveControls}
        </div>
      </div>
    </li>
  );
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
