import { FileDetail } from "@/components/files/FileDetail";
import { MemoryProfileSplitEditor } from "@/components/files/MemoryProfileSplitEditor";
import { MemoryUpdatesView } from "@/components/files/MemoryUpdatesView";
import { AgentCoreSection } from "@/components/files/fileWorkbench/AgentCoreSection";
import { DetailTabs } from "@/components/files/fileWorkbench/DetailTabs";
import { WorkspaceSection } from "@/components/files/fileWorkbench/WorkspaceSection";
import {
  type Tab,
  clampRail,
  folderIdOf,
  loadAgentCoreExpanded,
  loadExpandedWs,
  loadRailWidth,
  saveAgentCoreExpanded,
  saveExpandedWs,
  saveRailWidth,
  tabKey,
} from "@/components/files/fileWorkbench/storage";
import { EmptyHint, InlineError } from "@/components/files/parts";
import { PendingSharedInvites } from "@/components/files/sharedSpaces/PendingSharedInvites";
import {
  ProjectsRailHeader,
  SharedSpaceSection,
} from "@/components/files/sharedSpaces/SharedSpaceSection";
import { SearchField } from "@/components/ui";
import { useConversations } from "@/hooks/useConversations";
import { getFolders } from "@/hooks/useFolders";
import { useSharedSpaces } from "@/hooks/useSharedSpaces";
import type { FileSource } from "@/lib/fileSource";
import { cn } from "@/lib/utils";
import {
  type SharedSpaceSummary,
  canWriteSharedSpace,
  sharedWsId,
} from "@/services/sharedSpaces";
import { createDocumentSource } from "@/services/sources/documentSource";
import {
  MEMORY_UPDATES_PATH,
  createMemorySource,
  isMemoryTopicPath,
  parseProjectMemoryFolderId,
  parseProjectProfilePath,
} from "@/services/sources/memorySource";
import {
  createCloudWorkspaceSource,
  resolveWorkspaceSource,
} from "@/services/sources/workspaceSource";
import type { WorkspaceInfo } from "@/services/workspaces";
import { FileText, FolderOpen, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** One row in the「项目」段 — personal `folder:` or multi-user `shared:`. */
type ProjectRailItem =
  | { kind: "folder"; ws: WorkspaceInfo; sortAt: number }
  | { kind: "shared"; space: SharedSpaceSummary; sortAt: number };

function msOrZero(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : 0;
}

/** Best-effort「最近活跃」for a folder: max conversation `updatedAt` in that project. */
function folderActivityMs(
  folderId: string,
  conversations: { folderId?: string | null; updatedAt: string }[],
): number {
  let max = 0;
  for (const c of conversations) {
    if (c.folderId !== folderId) continue;
    max = Math.max(max, msOrZero(c.updatedAt));
  }
  return max;
}

/** Synthetic workspace id every memory leaf's tab lives under — they belong to no real
 * workspace (private per-user data), so they're resolved to {@link createMemorySource}
 * directly (path-aware: one source serves all leaves) and exempted from the "workspace
 * gone → close its tabs" cleanup. */
const MEMORY_WS = "__memory__";

/** Synthetic workspace id every rule-doc tab lives under — user rules are private per-user
 * documents belonging to no real workspace, resolved to {@link createDocumentSource} directly
 * (path-aware: the tab path IS the doc id) and exempted from the "workspace gone → close its
 * tabs" cleanup, 照 {@link MEMORY_WS}. */
const RULES_WS = "__rules__";

/**
 * The cross-project 文件 hub's **split** file UI (VSCode 式左树右详情) — the merged
 * left rail stacks every workspace (= folder, cloud + local) as a **flat,
 * collapsible section** ({@link WorkspaceSection}): a header (chevron + name +
 * cloud/local badge + create buttons) over its file tree (其自带 {@link FileSource})。
 * 段**默认折叠**（只露根标题），点标题展开/收起、展开态持久化（`expandedWs`）；折叠时不
 * 挂载 {@link FileTree}，故云端 eager 源的「整树递归拉取」推迟到展开时才发——工作区一多时
 * 既清爽又省掉打开页面即 N 次全量请求。全部平铺、无「home / 其他项目」分区——只靠
 * cloud/local 徽标区分（用户 2026-06 决定）；多人 `shared:` 并入「项目」段、角标「共享」
 * （定案 B）。每个 `folder:` 项目展开后固定挂约定树 ``AgentCore/{规则,记忆}/``
 * （无内容也显示），再是文件树；顶层同样挂全局 ``AgentCore/``（规则 + 记忆 / 最近更新），
 * 不再双 pinned「AI 记忆 / 你的规则」rail。
 * 工作区一视同仁（工作区对称化 D1a 起不再有置顶的「我的工作区」默认壳——裸聊产文件时由服务端
 * 懒建一个 per 对话本地工作区，与云端裸聊同构）。The right pane is a **tab strip** — opening
 * files stacks tabs, each {@link FileDetail} stays mounted (hidden when inactive) so
 * switching never drops editor / draft state. The tree always stays visible (unlike
 * the swap-style {@link FileBrowser} used in narrow side panels).
 *
 * Workspace lifecycle (new file·folder / upload / reveal in OS / open chat /
 * clear files / delete conversation or delete project / rename) lives on each
 * root's **right-click menu** to keep the rail clean; the rail header is a
 * **name filter** only (real-time, case-insensitive substring over workspace
 * names; session-only, not persisted — it's a search, not a preference).
 * Reuses {@link FileTree} in its headerless `chrome={false}` form so per-source
 * CRUD / drag / fold all come for free.
 *
 * No longer the lens onto a *single* project's home — that page (`/folders/:id`) is
 * gone (双模式工作区 决策 #9, 端态 I): this is purely the file lens, and chats live
 * on `/conversations`. The two cross-link: a root's「查看对话」jumps here→there, and
 * `/conversations`「浏览文件」jumps there→here (via `focusWsId`, which expands +
 * highlights the target root).
 */
export function FileWorkbench({
  workspaces,
  isLoading,
  isError,
  onRetry,
  fsAvailable,
  showMemory,
  focusWsId,
  focusKey,
  openMemoryLeaf,
}: {
  workspaces: WorkspaceInfo[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  fsAvailable: boolean;
  /** Show the pinned ``AgentCore/`` convention tree atop the rail (规则 + 记忆).
   * Off for hosts that shouldn't surface it (e.g. side panels). */
  showMemory?: boolean;
  /** When navigated here with a target workspace (`/conversations`「浏览文件」),
   * auto-expand + highlight + scroll to that section（段默认折叠，故主动展开那一个）。
   * `focusKey` (= navigation key) makes re-focusing the same project on a later jump
   * fire again. */
  focusWsId?: string | null;
  /** When navigated here from a对话页「记忆已更新」card deep-link, open this exact memory
   * leaf as a tab (记忆更新对话内可见 §1.6). Gated on `focusKey` so it fires once per
   * navigation. Optional `projectId` falls back when `path` does not encode a folder id. */
  openMemoryLeaf?: {
    path: string;
    name: string;
    projectId?: string | null;
  } | null;
  focusKey?: string;
}) {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [railWidth, setRailWidth] = useState<number>(() => loadRailWidth());
  // 默认折叠的工作区段里，被展开过的那些（持久化）。详见 WS_EXPANDED_KEY 注释。
  const [expandedWs, setExpandedWs] = useState<Set<string>>(() =>
    loadExpandedWs(),
  );
  // 按名称实时过滤工作区（会话级瞬态，不持久化——它是搜索而非偏好）。
  const [filter, setFilter] = useState("");
  // 从 /conversations「浏览文件」跳来时高亮的工作区根（1.5s 后消失，呼应对话页的 flash）。
  const [flashWsId, setFlashWsId] = useState<string | null>(null);
  // 最近更新 / 对话卡深链到项目记忆时，强制展开该项目下的「记忆」节点（一次性，展开后清除）。
  const [revealMemoryFolderId, setRevealMemoryFolderId] = useState<
    string | null
  >(null);
  // 深链到主题叶时，同时展开对应作用域的「主题」子夹（folderId 或 "global"）。
  const [revealMemoryTopicsKey, setRevealMemoryTopicsKey] = useState<
    string | null
  >(null);
  const appliedFocusRef = useRef<string | null>(null);
  const appliedMemoryLeafRef = useRef<string | null>(null);

  const sharedQuery = useSharedSpaces();
  const sharedSpaces = useMemo(
    () => sharedQuery.data ?? [],
    [sharedQuery.data],
  );
  const conversations = useConversations();

  /** Project + bare scratch only — `shared:` rows come from {@link useSharedSpaces}. */
  const personalWorkspaces = useMemo(
    () => workspaces.filter((w) => !w.wsId.startsWith("shared:")),
    [workspaces],
  );

  const toggleWs = useCallback((wsId: string) => {
    setExpandedWs((prev) => {
      const next = new Set(prev);
      if (next.has(wsId)) next.delete(wsId);
      else next.add(wsId);
      saveExpandedWs(next);
      return next;
    });
  }, []);

  const expandWs = useCallback((wsId: string) => {
    setExpandedWs((prev) => {
      if (prev.has(wsId)) return prev;
      const next = new Set(prev).add(wsId);
      saveExpandedWs(next);
      return next;
    });
  }, []);

  const clearMemoryReveal = useCallback(() => {
    setRevealMemoryFolderId(null);
    setRevealMemoryTopicsKey(null);
  }, []);

  /** Expand project AgentCore (+ memory / topics) for a deep-linked leaf. */
  const revealMemoryInRail = useCallback(
    (path: string, projectId?: string | null) => {
      const folderId = parseProjectMemoryFolderId(path) ?? projectId ?? null;
      const openTopics = isMemoryTopicPath(path);
      setFilter("");
      if (folderId) {
        const wsId = `folder:${folderId}`;
        expandWs(wsId);
        const expandedAc = loadAgentCoreExpanded();
        expandedAc.add(folderId);
        saveAgentCoreExpanded(expandedAc);
        setRevealMemoryFolderId(folderId);
        setFlashWsId(wsId);
        window.setTimeout(() => setFlashWsId(null), 1500);
      }
      if (openTopics) {
        setRevealMemoryTopicsKey(folderId ?? "global");
      }
    },
    [expandWs],
  );

  // 拖拽分隔条调左栏宽度：拖动期用窗口级监听 + 锁 body 光标/选区（避免拖过右侧编辑器时选中文本），
  // 松手落盘最终宽度（持久化，下次进页面沿用）。
  const startRailDrag = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = railWidth;
    let latest = startW;
    const onMove = (ev: PointerEvent) => {
      latest = clampRail(startW + (ev.clientX - startX));
      setRailWidth(latest);
    };
    const onUp = () => {
      saveRailWidth(latest);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const nudgeRail = (delta: number) => {
    setRailWidth((w) => {
      const next = clampRail(w + delta);
      saveRailWidth(next);
      return next;
    });
  };

  // 工作区被删/消失 → 关掉它名下的标签页，并修正激活项。记忆 tab（合成 ws）不属任何工作区，
  // 故豁免，否则它会被立刻清掉。共享空间以 `shared:` ws_id 计。
  useEffect(() => {
    const liveWsIds = new Set([
      ...personalWorkspaces.map((w) => w.wsId),
      ...sharedSpaces.map((s) => s.ws_id || sharedWsId(s.id)),
    ]);
    const live = tabs.filter(
      (t) =>
        t.wsId === MEMORY_WS || t.wsId === RULES_WS || liveWsIds.has(t.wsId),
    );
    if (live.length === tabs.length) return;
    setTabs(live);
    if (activeKey && !live.some((t) => tabKey(t.wsId, t.path) === activeKey)) {
      setActiveKey(live.length ? tabKey(live[0].wsId, live[0].path) : null);
    }
  }, [personalWorkspaces, sharedSpaces, tabs, activeKey]);

  // 从 /conversations「浏览文件」跳来：自动展开 + 高亮 + 滚入目标工作区（段默认折叠，故这里
  // 主动展开那一个）。每个 focusKey（导航键）只应用一次，但等到工作区列表就绪后才生效（冷进入
  // /files 时列表可能尚未加载）。
  useEffect(() => {
    if (!focusWsId || !focusKey) return;
    if (appliedFocusRef.current === focusKey) return;
    const known =
      personalWorkspaces.some((w) => w.wsId === focusWsId) ||
      sharedSpaces.some((s) => (s.ws_id || sharedWsId(s.id)) === focusWsId);
    if (!known) return;
    appliedFocusRef.current = focusKey;
    setFilter(""); // 清掉过滤，避免目标工作区被筛掉而看不到
    expandWs(focusWsId);
    setFlashWsId(focusWsId);
    const t = setTimeout(() => setFlashWsId(null), 1500);
    return () => clearTimeout(t);
  }, [focusWsId, focusKey, personalWorkspaces, sharedSpaces, expandWs]);

  // 对话页「记忆已更新」卡片深链跳来：打开目标记忆叶子的 tab（记忆更新对话内可见 §1.6）。每个
  // focusKey（导航键）只应用一次。记忆源与工作区列表无关，故无需等 workspaces 就绪即可打开；
  // 项目画像叶子的双栏编辑器会在 workspaces 到位后自行解析项目名。内联开 tab 逻辑（与 openFile
  // 同义）避免依赖在其后定义的 openFile。项目叶子额外展开对应项目 +「记忆」节点；主题叶再展「主题」。
  useEffect(() => {
    if (!openMemoryLeaf || !focusKey) return;
    if (appliedMemoryLeafRef.current === focusKey) return;
    appliedMemoryLeafRef.current = focusKey;
    const { path, name, projectId } = openMemoryLeaf;
    const key = tabKey(MEMORY_WS, path);
    setTabs((prev) =>
      prev.some((t) => tabKey(t.wsId, t.path) === key)
        ? prev
        : [...prev, { wsId: MEMORY_WS, path, name }],
    );
    setActiveKey(key);
    revealMemoryInRail(path, projectId);
  }, [openMemoryLeaf, focusKey, revealMemoryInRail]);

  // 每个工作区一个稳定的 FileSource（树与详情共用，按 ws 复用，避免重复构建/反复重载）。
  const sourceByWs = useMemo(() => {
    const m = new Map<string, FileSource | null>();
    for (const w of personalWorkspaces)
      m.set(w.wsId, resolveWorkspaceSource(w, fsAvailable));
    for (const s of sharedSpaces) {
      const wsId = s.ws_id || sharedWsId(s.id);
      m.set(
        wsId,
        createCloudWorkspaceSource(wsId, s.name, {
          readonly: !canWriteSharedSpace(s.my_role),
        }),
      );
    }
    return m;
  }, [personalWorkspaces, sharedSpaces, fsAvailable]);

  // 记忆叶子的路径感知单一源（所有记忆叶子共用一例，按 tab path 解析作用域；与工作区源同构，
  // 故复用 FileDetail/编辑器）。
  const memorySource = useMemo(() => createMemorySource(), []);

  // 规则叶子的路径感知单一源（tab path 即文档 id；与记忆源同构，故复用 FileDetail/编辑器）。
  const documentSource = useMemo(() => createDocumentSource(), []);

  // 过滤只按工作区名（大小写不敏感子串）——本次只做工作区级筛选，不下探文件名。
  const visiblePersonal = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return personalWorkspaces;
    return personalWorkspaces.filter((w) => w.name.toLowerCase().includes(q));
  }, [personalWorkspaces, filter]);

  const visibleShared = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return sharedSpaces;
    return sharedSpaces.filter((s) => s.name.toLowerCase().includes(q));
  }, [sharedSpaces, filter]);

  /** folder: + shared: 混排进「项目」段（按最近活跃降序）。 */
  const projectItems = useMemo(() => {
    const items: ProjectRailItem[] = [];
    for (const ws of visiblePersonal) {
      if (!ws.wsId.startsWith("folder:")) continue;
      const folderId = folderIdOf(ws.wsId);
      items.push({
        kind: "folder",
        ws,
        sortAt: folderId ? folderActivityMs(folderId, conversations) : 0,
      });
    }
    for (const space of visibleShared) {
      items.push({
        kind: "shared",
        space,
        sortAt: msOrZero(space.updated_at),
      });
    }
    items.sort((a, b) => b.sortAt - a.sortAt);
    return items;
  }, [visiblePersonal, visibleShared, conversations]);

  const scratches = useMemo(
    () => visiblePersonal.filter((w) => w.wsId.startsWith("conv:")),
    [visiblePersonal],
  );

  const railEmpty =
    personalWorkspaces.length === 0 &&
    sharedSpaces.length === 0 &&
    !sharedQuery.isLoading;

  const activeTab = useMemo(
    () => tabs.find((t) => tabKey(t.wsId, t.path) === activeKey) ?? null,
    [tabs, activeKey],
  );

  // 打开文件：已开则激活其标签，未开则新增并激活（标签持久，直到手动关闭）。
  const openFile = (wsId: string, path: string, name: string) => {
    const key = tabKey(wsId, path);
    setTabs((prev) =>
      prev.some((t) => tabKey(t.wsId, t.path) === key)
        ? prev
        : [...prev, { wsId, path, name }],
    );
    setActiveKey(key);
  };

  /** Open a memory leaf and, for project-scoped paths, expand that project +「记忆」node. */
  const openMemoryLeafInRail = (
    path: string,
    name: string,
    projectId?: string | null,
  ) => {
    openFile(MEMORY_WS, path, name);
    revealMemoryInRail(path, projectId);
  };

  // 关标签：关的是激活页则跳到相邻页（优先右、否则左），全关则回空态。
  const closeTab = (key: string) => {
    const idx = tabs.findIndex((t) => tabKey(t.wsId, t.path) === key);
    if (idx === -1) return;
    const next = tabs.filter((_, i) => i !== idx);
    setTabs(next);
    if (activeKey === key) {
      const ni = Math.min(idx, next.length - 1);
      setActiveKey(ni >= 0 ? tabKey(next[ni].wsId, next[ni].path) : null);
    }
  };

  // 只留这一页（其余全关），并将其设为激活。
  const closeOthers = (key: string) => {
    const keep = tabs.find((t) => tabKey(t.wsId, t.path) === key);
    if (!keep) return;
    setTabs([keep]);
    setActiveKey(key);
  };

  const closeAll = () => {
    setTabs([]);
    setActiveKey(null);
  };

  return (
    <div className="flex h-full w-full">
      {/* Left: workspaces + their files as one multi-root tree (resizable). */}
      <aside
        style={{ width: railWidth }}
        className="flex shrink-0 flex-col border-r border-border"
      >
        {/* Rail header: workspace name filter only (新建走项目区 + 菜单；
            段级 CRUD 在各 WorkspaceSection / SharedSpaceSection 右键菜单). */}
        <div className="flex h-12 shrink-0 items-center gap-1 border-b border-border px-2">
          <SearchField
            value={filter}
            onValueChange={setFilter}
            placeholder="筛选工作区…"
            aria-label="按名称筛选工作区"
            className="min-w-0 flex-1"
          />
        </div>

        {/* Pinned global ``AgentCore/{规则,记忆}/`` — replaces dual「AI 记忆 / 你的规则」rails.
            Per-project convention tree mounts under each project folder. */}
        {showMemory && (
          <div className="shrink-0 border-b border-border px-2 py-1">
            <AgentCoreSection
              scope={{ kind: "global" }}
              memoryActivePath={
                activeTab?.wsId === MEMORY_WS ? activeTab.path : null
              }
              rulesActivePath={
                activeTab?.wsId === RULES_WS ? activeTab.path : null
              }
              onOpenMemory={(path, name) => openFile(MEMORY_WS, path, name)}
              onOpenRule={(path, name) => openFile(RULES_WS, path, name)}
              onMemoryTopicDeleted={(path) =>
                closeTab(tabKey(MEMORY_WS, path))
              }
              onRuleDeleted={(path) => closeTab(tabKey(RULES_WS, path))}
              onRuleRenamed={(path, name) =>
                setTabs((prev) =>
                  prev.map((t) =>
                    t.wsId === RULES_WS && t.path === path ? { ...t, name } : t,
                  ),
                )
              }
              onOpenUpdates={() =>
                openFile(MEMORY_WS, MEMORY_UPDATES_PATH, "记忆动态")
              }
              forceOpen={revealMemoryTopicsKey === "global"}
              forceOpenMemory={revealMemoryTopicsKey === "global"}
              forceOpenMemoryTopics={revealMemoryTopicsKey === "global"}
              onRevealApplied={clearMemoryReveal}
            />
          </div>
        )}

        <PendingSharedInvites
          onAccepted={(space: SharedSpaceSummary) => {
            const wsId = space.ws_id || sharedWsId(space.id);
            expandWs(wsId);
            setFlashWsId(wsId);
            window.setTimeout(() => setFlashWsId(null), 1500);
          }}
        />

        {isLoading || sharedQuery.isLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2
              size={18}
              className="animate-spin text-muted-foreground/50"
            />
          </div>
        ) : isError && sharedQuery.isError ? (
          <InlineError
            onRetry={() => {
              onRetry();
              void sharedQuery.refetch();
            }}
          />
        ) : railEmpty ? (
          <EmptyHint
            icon={<FolderOpen size={24} className="text-muted-foreground/40" />}
            title="还没有工作区"
            hint="新建项目或共享空间，或在对话里产生文件后，对应条目会出现在这里。"
          />
        ) : (
          <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 py-1">
            {filter.trim() &&
            projectItems.length === 0 &&
            scratches.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                没有名称匹配「{filter.trim()}」的工作区
              </p>
            ) : (
              <>
                {(projectItems.length > 0 || !filter.trim()) && (
                  <ProjectsRailHeader
                    onSharedCreated={(spaceId) => {
                      const wsId = sharedWsId(spaceId);
                      expandWs(wsId);
                      setFlashWsId(wsId);
                      window.setTimeout(() => setFlashWsId(null), 1500);
                    }}
                  />
                )}
                {projectItems.length === 0 && !filter.trim() ? (
                  <p className="px-2 py-2 text-xs text-muted-foreground/70">
                    还没有项目工作区
                  </p>
                ) : (
                  projectItems.map((item) => {
                    if (item.kind === "shared") {
                      const { space } = item;
                      const wsId = space.ws_id || sharedWsId(space.id);
                      return (
                        <SharedSpaceSection
                          key={space.id}
                          space={space}
                          source={sourceByWs.get(wsId) ?? null}
                          activePath={
                            activeTab?.wsId === wsId ? activeTab.path : null
                          }
                          expanded={expandedWs.has(wsId)}
                          onToggle={() => toggleWs(wsId)}
                          onOpenFile={(path, name) =>
                            openFile(wsId, path, name)
                          }
                          flashing={wsId === flashWsId}
                        />
                      );
                    }
                    const { ws } = item;
                    const folderId = folderIdOf(ws.wsId);
                    return (
                      <WorkspaceSection
                        key={ws.wsId}
                        ws={ws}
                        source={sourceByWs.get(ws.wsId) ?? null}
                        activePath={
                          activeTab?.wsId === ws.wsId ? activeTab.path : null
                        }
                        expanded={expandedWs.has(ws.wsId)}
                        onToggle={() => toggleWs(ws.wsId)}
                        onOpenFile={(path, name) =>
                          openFile(ws.wsId, path, name)
                        }
                        flashing={ws.wsId === flashWsId}
                        projectRail={
                          showMemory && folderId ? (
                            <AgentCoreSection
                              scope={{
                                kind: "project",
                                folderId,
                                projectName: ws.name,
                              }}
                              memoryActivePath={
                                activeTab?.wsId === MEMORY_WS
                                  ? activeTab.path
                                  : null
                              }
                              rulesActivePath={
                                activeTab?.wsId === RULES_WS
                                  ? activeTab.path
                                  : null
                              }
                              onOpenMemory={(path, name) =>
                                openFile(MEMORY_WS, path, name)
                              }
                              onOpenRule={(path, name) =>
                                openFile(RULES_WS, path, name)
                              }
                              onMemoryTopicDeleted={(path) =>
                                closeTab(tabKey(MEMORY_WS, path))
                              }
                              onRuleDeleted={(path) =>
                                closeTab(tabKey(RULES_WS, path))
                              }
                              onRuleRenamed={(path, name) =>
                                setTabs((prev) =>
                                  prev.map((t) =>
                                    t.wsId === RULES_WS && t.path === path
                                      ? { ...t, name }
                                      : t,
                                  ),
                                )
                              }
                              indent={14}
                              forceOpen={revealMemoryFolderId === folderId}
                              forceOpenMemory={
                                revealMemoryFolderId === folderId ||
                                revealMemoryTopicsKey === folderId
                              }
                              forceOpenMemoryTopics={
                                revealMemoryTopicsKey === folderId
                              }
                              onRevealApplied={clearMemoryReveal}
                            />
                          ) : undefined
                        }
                      />
                    );
                  })
                )}

                {(scratches.length > 0 || !filter.trim()) && (
                  <div className="px-2 pb-0.5 pt-3 text-xs font-medium text-muted-foreground">
                    对话工作区
                  </div>
                )}
                {scratches.length === 0 && !filter.trim() ? (
                  <p className="px-2 py-2 text-xs text-muted-foreground/70">
                    裸聊产生文件后会出现在这里
                  </p>
                ) : (
                  scratches.map((ws) => (
                    <WorkspaceSection
                      key={ws.wsId}
                      ws={ws}
                      source={sourceByWs.get(ws.wsId) ?? null}
                      activePath={
                        activeTab?.wsId === ws.wsId ? activeTab.path : null
                      }
                      expanded={expandedWs.has(ws.wsId)}
                      onToggle={() => toggleWs(ws.wsId)}
                      onOpenFile={(path, name) => openFile(ws.wsId, path, name)}
                      flashing={ws.wsId === flashWsId}
                    />
                  ))
                )}
              </>
            )}
          </div>
        )}
      </aside>

      {/* Draggable sash between tree and detail (keyboard: ←/→ to nudge). */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="调整文件树宽度"
        tabIndex={0}
        onPointerDown={startRailDrag}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") {
            e.preventDefault();
            nudgeRail(-16);
          } else if (e.key === "ArrowRight") {
            e.preventDefault();
            nudgeRail(16);
          }
        }}
        style={{ touchAction: "none" }}
        className="z-10 w-1.5 shrink-0 cursor-col-resize transition-colors hover:bg-primary/20 focus-visible:bg-primary/30 focus-visible:outline-none"
      />

      {/* Right: open files as tabs; every open file stays mounted (hidden when
          inactive) so switching never unmounts an editor or drops unsaved /
          transient state. */}
      <section className="flex min-w-0 flex-1 flex-col">
        {tabs.length === 0 ? (
          <EmptyHint
            inline
            icon={<FileText size={26} className="text-muted-foreground/40" />}
            title="选择一个文件"
            hint="从左侧的项目树里点开文件，可同时打开多个、用标签页来回切换。"
          />
        ) : (
          <>
            <DetailTabs
              tabs={tabs}
              activeKey={activeKey}
              onActivate={setActiveKey}
              onClose={closeTab}
              onCloseOthers={closeOthers}
              onCloseAll={closeAll}
            />
            <div className="relative min-h-0 flex-1">
              {tabs.map((t) => {
                const key = tabKey(t.wsId, t.path);
                // The synthetic「记忆动态」tab is not a file — render the cross-conversation
                // feed view instead of a source-backed editor.
                const isMemoryUpdates =
                  t.wsId === MEMORY_WS && t.path === MEMORY_UPDATES_PATH;
                const src =
                  t.wsId === MEMORY_WS
                    ? memorySource
                    : t.wsId === RULES_WS
                      ? documentSource
                      : (sourceByWs.get(t.wsId) ?? null);
                // A project's 画像 leaf opens the two-pane 全局+本项目 editor instead of a
                // lone file; resolve its live workspace name for the 归属 label (fall back
                // to stripping the tab name if the workspace is gone).
                const projFolderId =
                  t.wsId === MEMORY_WS ? parseProjectProfilePath(t.path) : null;
                const projName = projFolderId
                  ? (getFolders().find((f) => f.id === projFolderId)?.name ??
                    t.name.replace(/·画像\.md$/, ""))
                  : null;
                return (
                  <div
                    key={key}
                    className={cn(
                      "absolute inset-0",
                      key === activeKey ? "" : "hidden",
                    )}
                  >
                    {isMemoryUpdates ? (
                      <MemoryUpdatesView
                        onOpenLeaf={(path, name) =>
                          openMemoryLeafInRail(path, name)
                        }
                      />
                    ) : src ? (
                      projFolderId ? (
                        <MemoryProfileSplitEditor
                          source={src}
                          folderId={projFolderId}
                          projectName={
                            projName ?? t.name.replace(/·画像\.md$/, "")
                          }
                          onClose={() => closeTab(key)}
                        />
                      ) : (
                        <FileDetail
                          source={src}
                          path={t.path}
                          name={t.name}
                          onClose={() => closeTab(key)}
                        />
                      )
                    ) : (
                      <EmptyHint
                        inline
                        icon={
                          <FileText
                            size={26}
                            className="text-muted-foreground/40"
                          />
                        }
                        title="无法打开此文件"
                        hint="它所属项目的文件源暂不可用。"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
