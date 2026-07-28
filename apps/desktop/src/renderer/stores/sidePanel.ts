import { detachLocalBrowserHost } from "@/lib/detachLocalBrowserHost";
import { uiGet, uiSet } from "@/lib/uiStorage";
import { create } from "zustand";
import { useBrowserSessionsStore } from "./browserSessions";
import { useCommandPanelStore } from "./commandPanel";
import { useConversationStore } from "./conversation";
import { projectRuntime, revisionRootId, useExecutionStore } from "./execution";

/**
 * Unified conversation side panel (前端UX设计.md §十) — the chat's single
 * right-docked surface, modelled as ONE flat tab strip (方案 B · 图1式):
 *
 *  - fixed, non-closable 「工作区」 (first) + 「改动」 (second);
 *  - in canvas mode only: fixed, non-closable 「指挥台」(条件固定，不进 `+`);
 *  - closable content tabs (≤12, 固定不计): File 多实例、Terminal / Browser 各一壳
 *   （壳内各自管会话/页签）、run / endpoint / simple-turn 详情。
 *
 * Content tabs store references only; bodies keep-alive while the tab exists.
 * `open` / `width` are persisted; content tabs are session-level.
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

/** Cap on closable content tabs: opening beyond the limit drops the oldest (fixed tabs exempt). */
const MAX_TABS = 12;

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

/**
 * Reserved id of the conditional 「改动」 tab（有本对话 AI 文件改动或深链时出现；
 * 出现后位次第二、不可关；前端UX设计.md §十）。
 */
export const CHANGES_TAB_ID = "changes";

/** Reserved id of the fixed 「指挥台」 tab (canvas mode only; never closes; 不进 `+`). */
export const COMMAND_TAB_ID = "command";

/**
 * Stable content-tab id for the 右坞浏览器壳（顶栏可关内容 tab；`+` / 活动卡共用）。
 * 产物 HTML 完整预览亦走本 tab（`openWorkspaceHtmlInBrowser`）；旧平行「预览」tab 已拆除（M3b）。
 */
export const TEAM_BROWSER_TAB_ID = "browser:team";

/**
 * Stable content-tab id for the 右坞终端壳（顶栏可关；`+` / 后台进程活动共用）。
 * 多 pty / 后台进程 / 执行记录在壳内列表管理，不另开顶栏 tab。
 */
export const TEAM_TERMINAL_TAB_ID = "terminal:hub";

/** Auto-surface dismiss key for the terminal hub (scoped per conversation). */
export function terminalDismissKey(conversationId: string | null): string {
  return conversationId ? `terminal:${conversationId}` : "terminal";
}

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

/** Top-bar Terminal content tab — singleton hub; sessionId focuses a pty inside. */
export interface TerminalDetailTab {
  kind: "terminal";
  /** Dedup identity: always {@link TEAM_TERMINAL_TAB_ID}. */
  id: string;
  title: string;
  /** Preferred pty session to select inside the hub; null = panel default selection. */
  sessionId: string | null;
}

/** Top-bar File content tab — path reference only; body keep-alives FileDetail. */
export interface FileDetailTab {
  kind: "file";
  /** Dedup identity: `file:<path>`. */
  id: string;
  title: string;
  path: string;
  name: string;
}

/**
 * Top-bar Browser content tab — 右坞 {@link BrowserPanel} 壳（≠ `preview://`）。
 * 能力上通常一会话一实例；壳内多页签由 browserSessions store 管理。
 */
export interface BrowserDetailTab {
  kind: "browser";
  id: string;
  title: string;
}

/** A side-panel content tab (详情 / 终端 / 文件 / 浏览器). */
export type DetailTab =
  | RunDetailTab
  | ContentDetailTab
  | SimpleTurnDetailTab
  | TerminalDetailTab
  | FileDetailTab
  | BrowserDetailTab;

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

/** @deprecated Prefer {@link TEAM_TERMINAL_TAB_ID}; kept for call-site greps. */
export const terminalTabId = (_instanceId?: string): string =>
  TEAM_TERMINAL_TAB_ID;

export const fileTabId = (path: string): string => `file:${path}`;

let untitledFileSeq = 0;
function nextUntitledFileId(): string {
  untitledFileSeq += 1;
  return `u${untitledFileSeq}`;
}

interface SidePanelState {
  /** Panel visibility (persisted). */
  open: boolean;
  /** Docked width in px, clamped to [280, 动态上限] (persisted)；上限见 sidePanelMaxWidth()。 */
  width: number;
  /** Open content tabs (session-level; 固定 工作区 / 条件「改动」/ 指挥台 不在此数组). */
  tabs: DetailTab[];
  /**
   * Active tab: `WORKSPACE_TAB_ID` / `CHANGES_TAB_ID` / `COMMAND_TAB_ID`
   * or a content tab id. Defaults to the workspace home.
   */
  activeTabId: string;
  /**
   * 「改动」tab 聚焦的回合（产物卡「查看改动」写入）；亦作深链期间强制挂 tab 的信号。
   * 切对话时应清掉（避免旧 messageId 在无改动对话上空挂）。
   */
  changesFocusMessageId: string | null;
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

  /** Open (or re-focus) a content tab, deduped by id; reveals + activates it. */
  openTab: (
    tab: DetailTab,
    opts?: { activate?: boolean; reveal?: boolean },
  ) => void;
  /** Close a content tab; falls back to a neighbour tab, else the 工作区 home.
   * Never closes the panel (fixed tabs are always there). */
  closeTab: (id: string) => void;
  /** Activate a tab (fixed id or a content tab id). */
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
   * run / terminal / file / browser tabs. The canvas calls this when leaving its
   * reading context (放大态 exit / canvas→chat).
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
  /**
   * 揭示面板并激活「改动」tab（无 tab 时先挂再聚焦）；可选聚焦某回合。
   */
  showChanges: (messageId?: string | null) => void;
  /** 清除改动深链聚焦（切对话时调用）。 */
  clearChangesFocus: () => void;
  /** Open / focus a File content tab (path reference); reveals the panel. */
  showFile: (path: string, name: string) => void;
  /**
   * `+` → 文件：无路径时合理空态（打开一个占位文件 tab，提示从工作区点选）。
   * 有路径时等同 {@link showFile}。
   */
  openFileTab: (path?: string, name?: string) => void;
  /** `+` → 终端：开/聚焦唯一 Terminal 壳；可选绑定 preferred session。 */
  openTerminalTab: (opts?: {
    sessionId?: string | null;
    title?: string;
    activate?: boolean;
    reveal?: boolean;
  }) => string;
  /** Update the hub tab's preferred session (after async spawn). */
  bindTerminalSession: (
    tabId: string,
    sessionId: string,
    title?: string,
  ) => void;
  /** Clear hub preferredSessionId when that pty was closed. */
  clearTerminalPreferredSession: (sessionId: string) => void;
  /**
   * 揭示「浏览器」内容 tab（活动卡 / 登录升级卡 / `+` / 产物完整预览）：开面板 + 开/聚焦浏览器壳；
   * 无本地页签时建空白页。
   */
  showBrowser: () => void;
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
  // Content tabs are session-level, so a fresh load always starts on the workspace
  // home rather than a dangling tab id.
  activeTabId: WORKSPACE_TAB_ID,
  changesFocusMessageId: null,
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
    const reveal = opts?.reveal !== false;
    if (reveal) persistOpen(true);
    set((s) => {
      const exists = s.tabs.some((t) => t.id === tab.id);
      // A re-open replaces the tab wholesale (same id ⇒ same kind, namespaced
      // prefixes guarantee it), refreshing its title/scope without merging kinds.
      let tabs = exists
        ? s.tabs.map((t) => (t.id === tab.id ? tab : t))
        : [...s.tabs, tab];
      // Cap closable content tabs: a new tab beyond the limit pushes out the oldest.
      if (tabs.length > MAX_TABS) tabs = tabs.slice(tabs.length - MAX_TABS);
      const activate = opts?.activate !== false;
      return {
        tabs,
        ...(reveal ? { open: true as const, pendingBadge: 0 } : {}),
        activeTabId: activate ? tab.id : s.activeTabId,
      };
    });
  },

  closeTab: (id) => {
    const closing = get().tabs.find((t) => t.id === id);
    if (closing?.kind === "browser") {
      // 关浏览器 tab = 脱离保活（改 React 状态前显式 hide）。
      void detachLocalBrowserHost();
    }
    if (closing?.kind === "terminal") {
      const conversationId =
        useConversationStore.getState().currentConversationId;
      get().dismissAutoSurface(terminalDismissKey(conversationId));
    }
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

  showChanges: (messageId) => {
    persistOpen(true);
    set({
      open: true,
      activeTabId: CHANGES_TAB_ID,
      changesFocusMessageId: messageId ?? null,
      pendingBadge: 0,
    });
  },

  clearChangesFocus: () => {
    set((s) =>
      s.changesFocusMessageId == null ? s : { changesFocusMessageId: null },
    );
  },

  showFile: (path, name) => {
    get().openFileTab(path, name);
  },

  openFileTab: (path, name) => {
    if (path && name) {
      get().openTab({
        kind: "file",
        id: fileTabId(path),
        title: name,
        path,
        name,
      });
      return;
    }
    // `+` → 文件无路径：占位空态 tab（可多开；不与真实路径 file: 冲突）。
    const instanceId = nextUntitledFileId();
    get().openTab({
      kind: "file",
      id: `file:untitled:${instanceId}`,
      title: "文件",
      path: "",
      name: "",
    });
  },

  openTerminalTab: (opts) => {
    const id = TEAM_TERMINAL_TAB_ID;
    const conversationId =
      useConversationStore.getState().currentConversationId;
    // User explicitly opened (or auto-surface after dismiss cleared) → allow future auto-surface.
    get().clearAutoSurfaceDismiss(terminalDismissKey(conversationId));

    const state = get();
    const terminals = state.tabs.filter(
      (t): t is TerminalDetailTab => t.kind === "terminal",
    );
    const activeTerminal = terminals.find((t) => t.id === state.activeTabId);
    const existing =
      terminals.find((t) => t.id === id) ?? activeTerminal ?? terminals[0];
    const activeWasTerminal = Boolean(activeTerminal);

    // Collapse legacy multi-instance terminal tabs into the singleton hub.
    if (terminals.length > 1 || (existing && existing.id !== id)) {
      set((s) => ({
        tabs: s.tabs.filter((t) => t.kind !== "terminal"),
        activeTabId: activeWasTerminal ? id : s.activeTabId,
      }));
    }

    const sessionId =
      opts?.sessionId !== undefined
        ? opts.sessionId
        : (existing?.sessionId ?? null);
    get().openTab(
      {
        kind: "terminal",
        id,
        title: opts?.title ?? "终端",
        sessionId,
      },
      {
        activate: opts?.activate !== false,
        reveal: opts?.reveal,
      },
    );
    return id;
  },

  bindTerminalSession: (_tabId, sessionId, title) => {
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.kind === "terminal"
          ? {
              ...t,
              id: TEAM_TERMINAL_TAB_ID,
              sessionId,
              title: title ?? t.title,
            }
          : t,
      ),
    }));
  },

  clearTerminalPreferredSession: (sessionId) => {
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.kind === "terminal" && t.sessionId === sessionId
          ? { ...t, sessionId: null }
          : t,
      ),
    }));
  },

  showBrowser: () => {
    const conversationId =
      useConversationStore.getState().currentConversationId;
    get().openTab({
      kind: "browser",
      id: TEAM_BROWSER_TAB_ID,
      title: "浏览器",
    });
    // 先/并 hydrate：有 server session 时激活该页（merge 优先 activeSessionId），
    // 勿让 ensureBlank 的本地空白抢激活；仅无 server 页时才补空白。
    if (!conversationId) {
      useBrowserSessionsStore.getState().ensureBlankPage(null);
      return;
    }
    void useBrowserSessionsStore
      .getState()
      .hydrateConversation(conversationId)
      .then(() => {
        const pages = useBrowserSessionsStore
          .getState()
          .pagesFor(conversationId);
        const hasServer = pages.some(
          (p) => p.serverSessionId != null && p.serverSessionId !== "",
        );
        if (!hasServer) {
          useBrowserSessionsStore.getState().ensureBlankPage(conversationId);
        }
      })
      .catch(() => {
        useBrowserSessionsStore.getState().ensureBlankPage(conversationId);
      });
  },

  closePanel: () => {
    // 关坞 = 脱离保活（改 React 状态前显式 hide）。
    void detachLocalBrowserHost();
    persistOpen(false);
    recordActiveContextDismiss(get);
    set({ open: false });
  },

  togglePanel: () => {
    const next = !get().open;
    if (!next) {
      // 关坞 = 脱离保活。
      void detachLocalBrowserHost();
    }
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
