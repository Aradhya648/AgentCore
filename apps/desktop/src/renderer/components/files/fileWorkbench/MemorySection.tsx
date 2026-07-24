import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { isFeatureUnavailable } from "@/lib/errors";
import { notifyActionError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { listMemoryTopics, writeMemoryTopic } from "@/services/memory";
import {
  GLOBAL_PREFERENCES_PATH,
  GLOBAL_PROFILE_PATH,
  MEMORY_UPDATES_PATH,
  memoryProjectProfilePath,
  memoryTopicPath,
} from "@/services/sources/memorySource";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  FilePlus,
  FileText,
  Folder,
  FolderOpen,
  History,
  Loader2,
  SlidersHorizontal,
  Trash2,
  UserRound,
} from "lucide-react";
import { forwardRef, useEffect, useRef, useState } from "react";
import {
  loadMemoryCollapsed,
  loadMemoryProjectsExpanded,
  loadMemoryTopicsExpanded,
  saveMemoryCollapsed,
  saveMemoryProjectsExpanded,
  saveMemoryTopicsExpanded,
} from "./storage";

/** Which memory layer a section renders: the user's GLOBAL core, or one project's. */
export type MemoryScope =
  | { kind: "global" }
  | { kind: "project"; folderId: string; projectName: string };

/**
 * The folder-style「AI 记忆」rail section (Agent记忆与知识系统 §1.6) — a collapsible header over the
 * always-injected core leaves (偏好 global-only / 画像) **plus** a lazy 主题/ sub-folder of the
 * on-demand TOPIC notes (`consult_memory` pulls these; here they become browsable·editable·
 * deletable). GLOBAL mounts at the {@link FileWorkbench} rail root (最近更新 / 偏好 / 画像 / 主题);
 * each cloud project mounts its own project-scope section under the project folder (header「记忆」—
 * 画像 + 主题, scoped to that `folderId`).
 *
 * Deliberately NOT the generic {@link FileTree}: memory is AI-maintained by fixed sections
 * (防漂移), so the rail offers **打开 + (主题)删除 + (项目)新建主题** — no 改名 / 移动 / 上传.
 * Opening any leaf reuses the shared editor host via the path-aware memory `FileSource`;
 * 项目画像 routes to the 双栏 editor (`parseProjectProfilePath` → {@link MemoryProfileSplitEditor}).
 */
export function MemorySection({
  scope,
  activePath,
  onOpen,
  onTopicDeleted,
  onOpenUpdates,
  indent = 0,
  forceOpen = false,
  forceOpenTopics = false,
  onRevealApplied,
}: {
  scope: MemoryScope;
  /** The synthetic path of the open memory tab (highlights the matching row), or null. */
  activePath: string | null;
  /** Open a memory leaf in the detail pane (synthetic leaf path + display name). */
  onOpen: (path: string, name: string) => void;
  /** A topic was deleted — let the host close its tab if it is open (its synthetic path). */
  onTopicDeleted: (path: string) => void;
  /** Open the cross-conversation「记忆动态」feed. GLOBAL-only (memory writes are per-user,
   * not per-project), so only the rail-root section passes it. */
  onOpenUpdates?: () => void;
  /** Base left indent (px): 0 at the rail root, > 0 when nested under a project. */
  indent?: number;
  /** Deep-link reveal: force the section open (e.g. 最近更新 → project memory leaf). */
  forceOpen?: boolean;
  /** Deep-link reveal: also expand the「主题」sub-folder (topic leaf). */
  forceOpenTopics?: boolean;
  /** Host clears sticky reveal props after a one-shot expand (forceOpen must not stick). */
  onRevealApplied?: () => void;
}) {
  const folderId = scope.kind === "project" ? scope.folderId : null;
  const projectName = scope.kind === "project" ? scope.projectName : null;
  const scopeKey = folderId ?? "global";
  // Fold state persists per scope. 全局段默认展开（保住老肌肉记忆，只记「被折叠」）；项目「记忆」
  // 节点默认折叠（只记「被展开」）。
  const [sectionOpen, setSectionOpen] = useState(() =>
    scope.kind === "global"
      ? !loadMemoryCollapsed().has(scopeKey)
      : loadMemoryProjectsExpanded().has(scopeKey),
  );
  const [topicsOpen, setTopicsOpen] = useState(() =>
    loadMemoryTopicsExpanded().has(scopeKey),
  );
  const queryClient = useQueryClient();
  // One-shot: rising edge of forceOpen / forceOpenTopics applies once; collapse stays closed
  // even if the host briefly leaves the sticky prop true before clearing.
  const revealAppliedRef = useRef(false);

  useEffect(() => {
    if (!forceOpen && !forceOpenTopics) {
      revealAppliedRef.current = false;
      return;
    }
    if (revealAppliedRef.current) return;
    revealAppliedRef.current = true;

    if (forceOpen) {
      setSectionOpen((open) => {
        if (open) return open;
        if (scope.kind === "global") {
          const set = loadMemoryCollapsed();
          set.delete(scopeKey);
          saveMemoryCollapsed(set);
        } else {
          const set = loadMemoryProjectsExpanded();
          set.add(scopeKey);
          saveMemoryProjectsExpanded(set);
        }
        return true;
      });
    }
    if (forceOpenTopics) {
      setTopicsOpen((open) => {
        if (open) return open;
        const set = loadMemoryTopicsExpanded();
        set.add(scopeKey);
        saveMemoryTopicsExpanded(set);
        return true;
      });
    }
    onRevealApplied?.();
  }, [forceOpen, forceOpenTopics, scope.kind, scopeKey, onRevealApplied]);

  const toggleSection = () =>
    setSectionOpen((open) => {
      const next = !open;
      if (scope.kind === "global") {
        const set = loadMemoryCollapsed();
        if (next) set.delete(scopeKey);
        else set.add(scopeKey);
        saveMemoryCollapsed(set);
      } else {
        const set = loadMemoryProjectsExpanded();
        if (next) set.add(scopeKey);
        else set.delete(scopeKey);
        saveMemoryProjectsExpanded(set);
      }
      return next;
    });

  const toggleTopics = () =>
    setTopicsOpen((open) => {
      const next = !open;
      const set = loadMemoryTopicsExpanded();
      if (next) set.add(scopeKey);
      else set.delete(scopeKey);
      saveMemoryTopicsExpanded(set);
      return next;
    });

  const topics = useQuery({
    queryKey: ["memory-topics", scopeKey],
    queryFn: () => listMemoryTopics(folderId),
    enabled: topicsOpen,
    staleTime: 30_000,
    // A 404/501 = this deployed backend predates the 主题 endpoint (前后端版本漂移);
    // retrying can't fix it, so fail fast to the calm "暂不可用" state below instead of
    // hammering a route that will keep 404ing. Other errors keep the default retries.
    retry: (failureCount, error) =>
      !isFeatureUnavailable(error) && failureCount < 3,
  });

  const profilePath = folderId
    ? memoryProjectProfilePath(folderId)
    : GLOBAL_PROFILE_PATH;
  const profileName = projectName ? `${projectName}·画像.md` : "画像.md";

  const headerPad = indent + 8;
  const leafPad = indent + 26;
  const topicPad = indent + 44;

  const deleteTopic = async (slug: string) => {
    if (!window.confirm(`确定删除记忆主题「${slug}」？此操作不可撤销。`))
      return;
    try {
      const r = await writeMemoryTopic(slug, "", null, folderId);
      if (!r.ok) throw new Error("写入冲突");
      onTopicDeleted(memoryTopicPath(folderId, slug));
      await queryClient.invalidateQueries({
        queryKey: ["memory-topics", scopeKey],
      });
      notifySuccess("已删除记忆主题");
    } catch (e) {
      notifyActionError("删除失败", e);
    }
  };

  const createTopic = async () => {
    const input = window.prompt("主题名称");
    if (input === null) return;
    const slug = input.trim().replace(/\.md$/i, "").replace(/[\\/]/g, "-");
    if (!slug) return;
    const existing = topics.data ?? [];
    if (existing.includes(slug)) {
      onOpen(memoryTopicPath(folderId, slug), `${slug}.md`);
      return;
    }
    try {
      const r = await writeMemoryTopic(slug, `# ${slug}\n\n`, null, folderId);
      if (!r.ok) throw new Error("写入冲突");
      if (!topicsOpen) {
        setTopicsOpen(true);
        const set = loadMemoryTopicsExpanded();
        set.add(scopeKey);
        saveMemoryTopicsExpanded(set);
      }
      await queryClient.invalidateQueries({
        queryKey: ["memory-topics", scopeKey],
      });
      onOpen(memoryTopicPath(folderId, slug), `${slug}.md`);
      notifySuccess("已新建主题");
    } catch (e) {
      notifyActionError("新建主题失败", e);
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={toggleSection}
        aria-expanded={sectionOpen}
        style={{ paddingLeft: headerPad }}
        className={cn(
          "flex h-7 w-full items-center gap-1.5 rounded-lg pr-2 text-left text-sm text-foreground transition-colors hover:bg-accent/60",
          scope.kind === "global" && "font-medium",
        )}
      >
        {sectionOpen ? (
          <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-muted-foreground" />
        )}
        {scope.kind === "global" ? (
          <Brain size={14} className="shrink-0 text-primary" />
        ) : sectionOpen ? (
          <FolderOpen size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <Folder size={14} className="shrink-0 text-muted-foreground" />
        )}
        <span className="min-w-0 flex-1 truncate">
          {scope.kind === "global" ? "AI 记忆" : "记忆"}
        </span>
      </button>

      {sectionOpen && (
        <>
          {/* 记忆动态: the cross-conversation「最近更新」feed — the write side's home
              (记忆更新对话内可见 §1.6). GLOBAL-only, so it sits atop the rail-root section. */}
          {scope.kind === "global" && onOpenUpdates && (
            <MemoryLeafRow
              paddingLeft={leafPad}
              icon={
                <History size={14} className="shrink-0 text-muted-foreground" />
              }
              label="最近更新"
              active={activePath === MEMORY_UPDATES_PATH}
              onClick={onOpenUpdates}
            />
          )}
          {scope.kind === "global" && (
            <MemoryLeafRow
              paddingLeft={leafPad}
              icon={
                <SlidersHorizontal
                  size={14}
                  className="shrink-0 text-muted-foreground"
                />
              }
              label="偏好"
              active={activePath === GLOBAL_PREFERENCES_PATH}
              onClick={() => onOpen(GLOBAL_PREFERENCES_PATH, "偏好.md")}
            />
          )}
          <MemoryLeafRow
            paddingLeft={leafPad}
            icon={
              <UserRound size={14} className="shrink-0 text-muted-foreground" />
            }
            label="画像"
            active={activePath === profilePath}
            onClick={() => onOpen(profilePath, profileName)}
          />

          <button
            type="button"
            onClick={toggleTopics}
            aria-expanded={topicsOpen}
            title="按需查阅的记忆主题（consult_memory 拉取）"
            style={{ paddingLeft: leafPad }}
            className="flex h-7 w-full items-center gap-1.5 rounded-lg pr-2 text-left text-sm text-foreground transition-colors hover:bg-accent/60"
          >
            {topicsOpen ? (
              <ChevronDown
                size={14}
                className="shrink-0 text-muted-foreground"
              />
            ) : (
              <ChevronRight
                size={14}
                className="shrink-0 text-muted-foreground"
              />
            )}
            {topicsOpen ? (
              <FolderOpen
                size={14}
                className="shrink-0 text-muted-foreground"
              />
            ) : (
              <Folder size={14} className="shrink-0 text-muted-foreground" />
            )}
            <span className="min-w-0 flex-1 truncate">主题</span>
          </button>

          {topicsOpen &&
            (topics.isLoading ? (
              <div
                className="flex h-7 items-center gap-1.5 text-xs text-muted-foreground"
                style={{ paddingLeft: topicPad }}
              >
                <Loader2 size={12} className="animate-spin" />
                加载中…
              </div>
            ) : topics.isError ? (
              isFeatureUnavailable(topics.error) ? (
                // The deployed backend lacks the 主题 endpoint (前后端版本漂移). Not the
                // user's fault and no retry can fix it, so state it calmly (muted, no
                // red, no retry button) — resolves once the backend is upgraded.
                <div
                  title="服务端升级后自动恢复"
                  className="flex min-h-7 items-center py-1 text-xs text-muted-foreground/60"
                  style={{ paddingLeft: topicPad }}
                >
                  主题记忆暂不可用（服务端待升级）
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => void topics.refetch()}
                  style={{ paddingLeft: topicPad }}
                  className="flex h-7 w-full items-center gap-1 text-left text-xs text-destructive/80 hover:underline"
                >
                  加载失败，点此重试
                </button>
              )
            ) : (topics.data ?? []).length === 0 ? (
              scope.kind === "project" ? (
                <div
                  className="flex flex-col gap-1 py-1"
                  style={{ paddingLeft: topicPad }}
                >
                  <p className="text-xs text-muted-foreground/60">
                    本项目还没有记忆
                  </p>
                  <button
                    type="button"
                    onClick={() => void createTopic()}
                    className="flex h-7 w-fit items-center gap-1.5 rounded-lg pr-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
                  >
                    <FilePlus size={14} className="shrink-0" />
                    新建
                  </button>
                </div>
              ) : (
                <div
                  className="flex h-7 items-center text-xs text-muted-foreground/60"
                  style={{ paddingLeft: topicPad }}
                >
                  还没有主题记忆
                </div>
              )
            ) : (
              (topics.data ?? []).map((slug) => {
                const path = memoryTopicPath(folderId, slug);
                return (
                  <ContextMenu key={slug}>
                    <ContextMenuTrigger asChild>
                      <MemoryLeafRow
                        paddingLeft={topicPad}
                        icon={
                          <FileText
                            size={14}
                            className="shrink-0 text-muted-foreground"
                          />
                        }
                        label={`${slug}.md`}
                        active={activePath === path}
                        onClick={() => onOpen(path, `${slug}.md`)}
                      />
                    </ContextMenuTrigger>
                    <ContextMenuContent className="min-w-36">
                      <ContextMenuItem
                        variant="danger"
                        onSelect={() => void deleteTopic(slug)}
                      >
                        <Trash2 size={14} className="shrink-0" />
                        <span className="flex-1 truncate">删除主题</span>
                      </ContextMenuItem>
                    </ContextMenuContent>
                  </ContextMenu>
                );
              })
            ))}

          {/* Project memory: create when topics already exist (empty state has its own 新建). */}
          {scope.kind === "project" && (topics.data ?? []).length > 0 && (
            <button
              type="button"
              onClick={() => void createTopic()}
              style={{ paddingLeft: leafPad }}
              className="flex h-7 w-full items-center gap-1.5 rounded-lg pr-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
            >
              <FilePlus size={14} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate">新建主题</span>
            </button>
          )}
        </>
      )}
    </div>
  );
}

/** A single memory leaf row (偏好 / 画像 / 主题 note) — a slim button styled like the rail. */
const MemoryLeafRow = forwardRef<
  HTMLButtonElement,
  {
    paddingLeft: number;
    icon: React.ReactNode;
    label: string;
    active: boolean;
    onClick: () => void;
  }
>(function MemoryLeafRow(
  { paddingLeft, icon, label, active, onClick, ...rest },
  ref,
) {
  return (
    <button
      type="button"
      ref={ref}
      onClick={onClick}
      {...rest}
      style={{ paddingLeft }}
      className={cn(
        "flex h-7 w-full items-center gap-1.5 rounded-lg pr-2 text-left text-sm transition-colors",
        active
          ? "bg-accent text-foreground"
          : "text-foreground hover:bg-accent/60",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
});
MemoryLeafRow.displayName = "MemoryLeafRow";
