import { uiGet, uiSet } from "@/lib/uiStorage";
import { create } from "zustand";
import { useCommandPanelStore } from "./commandPanel";
import { useConversationStore } from "./conversation";
import { projectRuntime, revisionRootId, useExecutionStore } from "./execution";

/**
 * Unified conversation side panel (前端UX设计.md §十) — the chat's single
 * right-docked surface, modelled as ONE flat tab strip:
 *
 *  - a fixed, non-closable 「工作区」 home tab (the cloud↔local mode bar + the
 *    files body, with 快照 / 交接 as on-demand overlays), always first;
 *  - in canvas mode only: a fixed, non-closable 「指挥台」 tab (boss decisions /
 *    救火 / 后台云端任务), always second — not a closable run/content detail;
 *  - a closable detail tab per drill: one run-detail tab per revision chain
 *    (or standalone run) from an inline-graph worker node, a content tab for an
 *    endpoint bubble (提问 / 最终回答), or a simple-turn Q&A tab for a canvas
 *    SimpleTurn light card (前端UX设计.md §五/§六).
 *
 * There is no separate "detail mode" — the detail tabs ARE the detail, so the panel
 * never shows an empty detail placeholder. `open` / `width` are persisted; the detail
 * tabs are session-level (rebuilt from the execution slot / live messages).
 */

/** Resize bounds for the panel. */
const MIN_WIDTH = 280;
/**
 * 面板宽度上限改为「相对窗口」的动态值（行业主流：VS Code 靠主区最小宽反向约束、
 * Claude Artifacts / CSS clamp 用窗口百分比）——固定像素上限在大屏太窄、在小屏又会
 * 挤压中间对话区。上限 = min(硬上限, 窗口宽 × 比例)，随窗口自适应。
 */
const MAX_WIDTH_RATIO = 0.6;
/** 超宽屏兜底：再宽的显示器也不让单个面板超过此像素，避免主区被过度挤压。 */
const MAX_WIDTH_CAP = 960;
/** window 不可用时（无布局环境 / 早期单测）估算视口用的兜底宽度。 */
const FALLBACK_VIEWPORT = 1280;
const DEFAULT_WIDTH = 400;

/** Cap on run-detail tabs: opening a 7th drops the oldest (工作区 is exempt). */
const MAX_TABS = 6;

const OPEN_KEY = "side-panel-open";
const WIDTH_KEY = "side-panel-width";

/**
 * 当前视口下的面板宽度上限：min(硬上限, 窗口宽 × 比例)，且不低于 MIN_WIDTH（极窄窗口）。
 * 动态值，故导出为函数而非常量——拖拽 clamp、窗口 resize 收敛、双击复位都以它为准。
 */
export function sidePanelMaxWidth(): number {
  const viewport =
    typeof window !== "undefined" && window.innerWidth
      ? window.innerWidth
      : FALLBACK_VIEWPORT;
  return Math.max(
    MIN_WIDTH,
    Math.min(MAX_WIDTH_CAP, Math.round(viewport * MAX_WIDTH_RATIO)),
  );
}

export const SIDE_PANEL_MIN_WIDTH = MIN_WIDTH;
export const SIDE_PANEL_DEFAULT_WIDTH = DEFAULT_WIDTH;
export const SIDE_PANEL_MAX_TABS = MAX_TABS;

/** Reserved id of the fixed 「工作区」 home tab (always first, never closes). */
export const WORKSPACE_TAB_ID = "workspace";

/** Reserved id of the fixed 「指挥台」 tab (canvas mode only; always second, never closes). */
export const COMMAND_TAB_ID = "command";

/** Reserved id of the fixed 「终端」 tab（有后台进程或本对话执行记录才出现；不绑画布）。 */
export const TERMINAL_TAB_ID = "terminal";

/** Reserved id of the 「预览」 tab（应用内内置浏览器；仅当 `previewTab` 有值时出现；可关闭）。 */
export const PREVIEW_TAB_ID = "preview";

/** Reserved id of the 「浏览器直播」 tab（L3 团队浏览器 M1；仅当 `browserLiveTab` 有值时出现；可关闭）。 */
export const BROWSER_LIVE_TAB_ID = "browser-live";

/** After the last closable detail tab closes → 工作区。 */
function homeTabAfterDetailClose(): string {
  return WORKSPACE_TAB_ID;
}

const clampWidth = (w: number): number =>
  Math.max(MIN_WIDTH, Math.min(sidePanelMaxWidth(), Math.round(w)));

function loadOpen(): boolean {
  return uiGet<boolean>(OPEN_KEY) === true;
}

function loadWidth(): number {
  const raw = uiGet<number>(WIDTH_KEY);
  return typeof raw === "number" && Number.isFinite(raw)
    ? clampWidth(raw)
    : DEFAULT_WIDTH;
}

function persistOpen(open: boolean): void {
  uiSet(OPEN_KEY, open);
}

function persistWidth(width: number): void {
  uiSet(WIDTH_KEY, width);
}

/** Record dismiss for whichever auto-surface context is currently active. */
function recordActiveContextDismiss(
  get: () => Pick<SidePanelState, "dismissAutoSurface">,
): void {
  const commandActive = useCommandPanelStore.getState().active;
  const conversationId = useConversationStore.getState().currentConversationId;
  if (commandActive && conversationId) {
    get().dismissAutoSurface(`command:${conversationId}`);
  }
}

/**
 * A run-detail tab — one per revision chain (tab id = chain root) or standalone
 * run. Clicking an inline graph node pins that run here (前端UX设计.md §十);
 * switching rounds/chips updates `runId` in place without a new tab. Scoped by
 * message so two turns that each pin a run never collide in the strip (§9.3).
 */
export interface RunDetailTab {
  /** Discriminator: a worker run's structured detail (RunDetailBody). */
  kind: "run";
  /** Dedup identity: `run-detail:<messageId>:<chainRootOrRunId>`. */
  id: string;
  /** Label shown in the tab strip (the agent's role). */
  title: string;
  /** The assistant message whose execution slot holds this run. */
  messageId: string;
  /** The run currently shown in this tab (may be a revision of the chain root). */
  runId: string;
}

/**
 * A content tab — the turn's endpoint chat bubble (the user's prompt or the CEO's
 * final answer) surfaced in the docked panel. The canvas (放大态 / 聚焦节点) has no
 * chat column alongside, so an endpoint reads here — like a worker drill — instead
 * of a foot drawer (前端UX设计.md §五/§六). Endpoints are bubbles, not runs, so they
 * ride this kind rather than RunDetailBody. Scoped by the turn (`messageId`) so it
 * lights that graph's endpoint node; `contentMessageId` is the bubble rendered.
 */
/** Which endpoint a content tab stands for — drives its tab-strip icon (提问 vs
 * 最终回答), mirroring the graph endpoint nodes (用户输入 / CEO 汇聚点). */
export type EndpointKind = "prompt" | "answer";

export interface ContentDetailTab {
  /** Discriminator: a chat bubble rendered as Markdown (no run). */
  kind: "content";
  /** Dedup identity: `content-detail:<messageId>:<contentMessageId>`. */
  id: string;
  /** Label shown in the tab strip (提问 / 最终回答). */
  title: string;
  /** The turn (assistant message owning the execution) this endpoint belongs to. */
  messageId: string;
  /** The chat message whose content is rendered (the prompt / the final answer). */
  contentMessageId: string;
  /** The endpoint this bubble stands for — the user's prompt / the CEO's answer. */
  endpoint: EndpointKind;
}

/**
 * A simple-turn Q&A tab — the whole CEO-only exchange (user prompt + assistant
 * answer) from a canvas `SimpleTurn` light card. Pure dialogue has no execution
 * plan, so it must not ride `content` (whose live check requires a plan) or
 * `run` (前端UX设计.md §6.1 / §十).
 */
export interface SimpleTurnDetailTab {
  /** Discriminator: full Q&A for a no-execution turn. */
  kind: "simple-turn";
  /** Dedup identity: `simple-turn:<messageId>`. */
  id: string;
  /** Label shown in the tab strip (对话). */
  title: string;
  /** The turn key (assistant projection id) this Q&A belongs to. */
  messageId: string;
  /** The user message bubble rendered under 「提问」. */
  promptMessageId: string;
  /** The assistant message bubble rendered under 「回答」. */
  answerMessageId: string;
}

/** A side-panel detail tab: a worker run, an endpoint bubble, or a simple-turn Q&A. */
export type DetailTab = RunDetailTab | ContentDetailTab | SimpleTurnDetailTab;

/** Tab-strip id for a run detail. Prefer the continuation-chain root so all beats
 * of the same speaker share one tab; pass the root (or the run itself when it
 * has no `continuesRunId`). */
export const runDetailTabId = (messageId: string, runId: string): string =>
  `run-detail:${messageId}:${runId}`;

export const contentDetailTabId = (
  messageId: string,
  contentMessageId: string,
): string => `content-detail:${messageId}:${contentMessageId}`;

export const simpleTurnDetailTabId = (messageId: string): string =>
  `simple-turn:${messageId}`;

interface SidePanelState {
  /** Panel visibility (persisted). */
  open: boolean;
  /** Docked width in px, clamped to [280, 动态上限] (persisted)；上限见 sidePanelMaxWidth()。 */
  width: number;
  /** Open detail tabs (run / content / simple-turn), left→right (session-level;
   * stale run/content tabs are filtered at render against the live projection;
   * simple-turn tabs stay live without a plan). The 工作区 home tab is implicit
   * and is NOT part of this array. */
  tabs: DetailTab[];
  /** Active tab: `WORKSPACE_TAB_ID` / `COMMAND_TAB_ID` / `TERMINAL_TAB_ID` for fixed tabs, else a detail
   * tab id. Defaults to the workspace home so a manual open lands on the project files. */
  activeTabId: string;
  /**
   * A file the chat asked to preview (clicking a 产出文件 card row): the workspace
   * file browser watches this, opens the path in its swap-style preview, then
   * clears it. `nonce` lets the same path re-fire (re-click). Session-only.
   */
  pendingFilePreview: { path: string; name: string; nonce: number } | null;
  /**
   * 应用内「完整预览」（内置浏览器）当前打开的目标：会话 id + 入口 HTML 相对路径 + 展示名。
   * 非 null → SidePanel 出现可关闭的「预览」tab，激活时挂原生 WebContentsView（见
   * components/workspace/EmbeddedPreview）。null = 未打开。会话级（不持久）。
   */
  previewTab: { conversationId: string; path: string; name: string } | null;
  /**
   * L3「团队浏览器」M1 直播 (提案 D15)：当前打开直播的会话 id。非 null → SidePanel 出现可关闭的
   * 「浏览器直播」tab（激活时挂 {@link BrowserLivePanel} 附着 SSE 直播流）。null = 未打开。会话级
   * （不持久）；帧走 live-only 旁路通道、不进 journal/回放。tab 打开后跨 turn 存续，直到用户关闭。
   */
  browserLiveTab: { conversationId: string } | null;
  /**
   * Session-level memory of contexts where the user explicitly closed the panel,
   * blocking auto-surface until the panel is opened again or the context clears.
   */
  dismissedContexts: Set<string>;
  /**
   * Count of auto-surface events suppressed while the panel was dismissed — shown
   * as a badge on the panel toggle when the dock is closed.
   */
  pendingBadge: number;

  /** Record that auto-surface should not reopen the panel for this context. */
  dismissAutoSurface: (contextId: string) => void;
  isAutoSurfaceDismissed: (contextId: string) => boolean;
  clearAutoSurfaceDismiss: (contextId: string) => void;
  /** Bump the toggle badge when auto-surface is blocked by a dismiss. */
  incrementPendingBadge: () => void;

  /** Open (or re-focus) a detail tab, deduped by id; reveals + activates it. */
  openTab: (tab: DetailTab, opts?: { activate?: boolean }) => void;
  /** Close a detail tab; falls back to a neighbour tab, else the 工作区 home.
   * Never closes the panel (the home tab is always there). */
  closeTab: (id: string) => void;
  /** Activate a tab (`WORKSPACE_TAB_ID` / `COMMAND_TAB_ID` / `TERMINAL_TAB_ID` or a detail tab id). */
  setActiveTab: (id: string) => void;
  /**
   * Pin a run (of a specific message's turn) and reveal it. The inline graph
   * highlights whatever run tab is active for that turn, so opening / switching
   * / closing tabs keeps the graph in sync (§9.3).
   */
  showRunDetail: (messageId: string, runId: string, title?: string) => void;
  /**
   * Pin an endpoint chat bubble (the turn's prompt / final answer) and reveal it.
   * The canvas surfaces an endpoint here (no chat column alongside); the inline
   * graph lights the matching endpoint node while its content tab is active.
   */
  showContentDetail: (
    messageId: string,
    contentMessageId: string,
    title: string,
    endpoint: EndpointKind,
  ) => void;
  /**
   * Pin a simple-turn Q&A (user prompt + assistant answer) and reveal it. Used by
   * canvas `SimpleTurn` light cards — no execution, so not a run/content tab.
   */
  showSimpleTurnDetail: (
    messageId: string,
    promptMessageId: string,
    answerMessageId: string,
    title?: string,
  ) => void;
  /**
   * Drop every reading-context tab (endpoint content + simple-turn Q&A), keeping
   * run tabs. The canvas calls this when leaving its reading context (放大态 exit /
   * canvas→chat) so a surfaced 提问 / 最终回答 / 对话 never lingers beside the chat
   * bubble that already shows it.
   */
  closeContentTabs: () => void;
  /**
   * Reveal the panel WITHOUT touching the active tab — used by the 指挥台 tab's
   * auto-surface (前端UX设计.md §6.2) so a newly-arrived decision opens the dock while
   * a run/workspace tab the user is reading stays put (only the 指挥台 tab badge updates).
   */
  openPanel: () => void;
  /** Reveal the panel on the 工作区 home tab (the chat toggle / Ctrl+J). */
  showWorkspace: () => void;
  /** Reveal the 工作区 home tab AND request a file preview (产出文件 card click). */
  showFile: (path: string, name: string) => void;
  /** Consume the pending file-preview request once the files view has applied it. */
  clearFilePreview: () => void;
  /**
   * 打开应用内「完整预览」内置浏览器 tab（取代旧独立子窗口）：记下目标、开面板、切到「预览」
   * tab。EmbeddedPreview 组件据此挂原生视图并上报 bounds。同一 tab 复用（换文件即换目标）。
   */
  openPreview: (conversationId: string, path: string, name: string) => void;
  /**
   * 关闭「预览」tab：销毁原生内嵌视图（经 previewApi.embedClose）、清目标；若当前正处「预览」
   * tab 则回落 工作区 home。关闭 tab X、切换会话时调用。
   */
  closePreview: () => void;
  /**
   * 打开「浏览器直播」tab（提案 D15，入口 = 活动卡运行中的「查看直播」）：记下会话、开面板、切到直播
   * tab。同一 tab 复用（换会话即换目标）。
   */
  openBrowserLive: (conversationId: string) => void;
  /**
   * 关闭「浏览器直播」tab：清目标；若当前正处直播 tab 则回落 工作区 home。SSE 连接由 BrowserLivePanel
   * 卸载时自行收口（无原生视图需销毁）。关闭 tab X、切换会话时调用。
   */
  closeBrowserLive: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  setWidth: (width: number) => void;
  /** 窗口尺寸变化后把当前宽度收敛到新的动态上限（仅在越界时写入）。 */
  reclampWidth: () => void;
  /** 双击 resize 手柄：在 最小 / 默认 / 最大 三档间循环（窄屏 default==max 时自动去重）。 */
  cycleWidth: () => void;
}

export const useSidePanelStore = create<SidePanelState>((set, get) => ({
  open: loadOpen(),
  width: loadWidth(),
  tabs: [],
  // Detail tabs are session-level (rebuilt from the execution slot / live
  // messages), so a fresh load always starts on the workspace home rather than a
  // dangling tab id.
  activeTabId: WORKSPACE_TAB_ID,
  pendingFilePreview: null,
  previewTab: null,
  browserLiveTab: null,
  dismissedContexts: new Set(),
  pendingBadge: 0,

  dismissAutoSurface: (contextId) => {
    set((s) => {
      const dismissedContexts = new Set(s.dismissedContexts);
      dismissedContexts.add(contextId);
      return { dismissedContexts };
    });
  },

  isAutoSurfaceDismissed: (contextId) => get().dismissedContexts.has(contextId),

  clearAutoSurfaceDismiss: (contextId) => {
    set((s) => {
      if (!s.dismissedContexts.has(contextId)) return s;
      const dismissedContexts = new Set(s.dismissedContexts);
      dismissedContexts.delete(contextId);
      return { dismissedContexts };
    });
  },

  incrementPendingBadge: () =>
    set((s) => ({ pendingBadge: s.pendingBadge + 1 })),

  openTab: (tab, opts) => {
    persistOpen(true);
    set((s) => {
      const exists = s.tabs.some((t) => t.id === tab.id);
      // A re-open replaces the tab wholesale (same id ⇒ same kind, namespaced
      // prefixes guarantee it), refreshing its title/scope without merging kinds.
      let tabs = exists
        ? s.tabs.map((t) => (t.id === tab.id ? tab : t))
        : [...s.tabs, tab];
      // Cap the run-tab strip: a new tab beyond the limit pushes out the oldest.
      if (tabs.length > MAX_TABS) tabs = tabs.slice(tabs.length - MAX_TABS);
      const activate = opts?.activate !== false;
      return {
        tabs,
        open: true,
        activeTabId: activate ? tab.id : s.activeTabId,
      };
    });
  },

  closeTab: (id) => {
    set((s) => {
      const idx = s.tabs.findIndex((t) => t.id === id);
      const tabs = s.tabs.filter((t) => t.id !== id);
      let activeTabId = s.activeTabId;
      if (s.activeTabId === id) {
        // Fall back to the neighbour detail tab (next, else previous), else home.
        const next = tabs[idx] ?? tabs[idx - 1] ?? null;
        activeTabId = next ? next.id : homeTabAfterDetailClose();
      }
      return { tabs, activeTabId };
    });
  },

  setActiveTab: (id) => set({ activeTabId: id }),

  showRunDetail: (messageId, runId, title) => {
    // Same revision chain → one tab keyed by the chain root; `runId` tracks the
    // beat currently shown (graph node / 轮次 chip). Non-revision runs keep a
    // 1:1 tab. If the turn isn't projected yet, fall back to the clicked id.
    const rt = useExecutionStore.getState().byId[messageId];
    const projected = rt ? projectRuntime(rt) : null;
    const tabKeyRunId = projected
      ? revisionRootId(runId, projected.runs)
      : runId;
    get().openTab({
      kind: "run",
      id: runDetailTabId(messageId, tabKeyRunId),
      title: title ?? "详情",
      messageId,
      runId,
    });
  },

  showContentDetail: (messageId, contentMessageId, title, endpoint) => {
    get().openTab({
      kind: "content",
      id: contentDetailTabId(messageId, contentMessageId),
      title,
      messageId,
      contentMessageId,
      endpoint,
    });
  },

  showSimpleTurnDetail: (
    messageId,
    promptMessageId,
    answerMessageId,
    title,
  ) => {
    get().openTab({
      kind: "simple-turn",
      id: simpleTurnDetailTabId(messageId),
      title: title ?? "对话",
      messageId,
      promptMessageId,
      answerMessageId,
    });
  },

  closeContentTabs: () => {
    set((s) => {
      const tabs = s.tabs.filter(
        (t) => t.kind !== "content" && t.kind !== "simple-turn",
      );
      if (tabs.length === s.tabs.length) return s;
      // If the dropped tab was active, fall back to a surviving detail tab (e.g. a
      // run drilled in the canvas, kept per §十) else the 工作区 home.
      const activeStillThere = tabs.some((t) => t.id === s.activeTabId);
      const activeTabId = activeStillThere
        ? s.activeTabId
        : (tabs[tabs.length - 1]?.id ?? homeTabAfterDetailClose());
      return { tabs, activeTabId };
    });
  },

  openPanel: () => {
    persistOpen(true);
    set({ open: true, pendingBadge: 0 });
  },

  showWorkspace: () => {
    persistOpen(true);
    set({ open: true, activeTabId: WORKSPACE_TAB_ID, pendingBadge: 0 });
  },

  showFile: (path, name) => {
    persistOpen(true);
    set((s) => ({
      open: true,
      activeTabId: WORKSPACE_TAB_ID,
      pendingFilePreview: {
        path,
        name,
        nonce: (s.pendingFilePreview?.nonce ?? 0) + 1,
      },
    }));
  },

  clearFilePreview: () => set({ pendingFilePreview: null }),

  openPreview: (conversationId, path, name) => {
    persistOpen(true);
    set({
      open: true,
      activeTabId: PREVIEW_TAB_ID,
      previewTab: { conversationId, path, name },
      pendingBadge: 0,
    });
  },

  closePreview: () => {
    // 销毁原生内嵌视图（renderer 侧唯一销毁出口；hide 只在组件卸载时用）。web / 单测无 previewApi
    // → 可选链安全跳过。
    if (typeof window !== "undefined") window.previewApi?.embedClose();
    set((s) => {
      if (!s.previewTab && s.activeTabId !== PREVIEW_TAB_ID) return s;
      const activeTabId =
        s.activeTabId === PREVIEW_TAB_ID ? WORKSPACE_TAB_ID : s.activeTabId;
      return { previewTab: null, activeTabId };
    });
  },

  openBrowserLive: (conversationId) => {
    persistOpen(true);
    set({
      open: true,
      activeTabId: BROWSER_LIVE_TAB_ID,
      browserLiveTab: { conversationId },
      pendingBadge: 0,
    });
  },

  closeBrowserLive: () => {
    set((s) => {
      if (!s.browserLiveTab && s.activeTabId !== BROWSER_LIVE_TAB_ID) return s;
      const activeTabId =
        s.activeTabId === BROWSER_LIVE_TAB_ID
          ? WORKSPACE_TAB_ID
          : s.activeTabId;
      return { browserLiveTab: null, activeTabId };
    });
  },

  closePanel: () => {
    persistOpen(false);
    recordActiveContextDismiss(get);
    set({ open: false });
  },

  togglePanel: () => {
    const next = !get().open;
    persistOpen(next);
    if (!next) recordActiveContextDismiss(get);
    set({ open: next, pendingBadge: next ? 0 : get().pendingBadge });
  },

  setWidth: (width) => {
    const clamped = clampWidth(width);
    persistWidth(clamped);
    set({ width: clamped });
  },

  reclampWidth: () => {
    const clamped = clampWidth(get().width);
    if (clamped === get().width) return;
    persistWidth(clamped);
    set({ width: clamped });
  },

  cycleWidth: () => {
    const max = sidePanelMaxWidth();
    // 窄屏时 default 可能 ≥ max，去重避免出现「同一档」的空转停顿。
    const stops = Array.from(
      new Set([MIN_WIDTH, Math.min(DEFAULT_WIDTH, max), max]),
    ).sort((a, b) => a - b);
    const cur = get().width;
    const EPS = 2;
    // 从小到大跳到下一档，到顶回到最小 → min → default → max → min 循环。
    const next = stops.find((s) => s > cur + EPS) ?? stops[0];
    persistWidth(next);
    set({ width: next });
  },
}));
