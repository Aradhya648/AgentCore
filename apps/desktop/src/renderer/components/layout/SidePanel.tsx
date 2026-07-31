import { Markdown } from "@/components/chat/Markdown";
import { RunDetailBody } from "@/components/chat/detail/RunDetailBody";
import { FileDetail } from "@/components/files/FileDetail";
import { EmptyHint } from "@/components/files/parts";
import {
  CommandPanelBody,
  useCommandRegion,
} from "@/components/graph/CanvasDecisionPanel";
import { KillPtyConfirmDialog } from "@/components/terminal/KillPtyConfirmDialog";
import {
  TerminalPanelBody,
  useTerminalRegion,
} from "@/components/terminal/TerminalPanel";
import { Button, IconButton } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useBrowserRegion } from "@/components/workspace/BrowserLivePanel";
import { BrowserPanel } from "@/components/workspace/BrowserPanel";
import { ConversationChangesPanel } from "@/components/workspace/ConversationChangesPanel";
import { WorkspaceMode } from "@/components/workspace/WorkspacePanel";
import { useConversationFileSource } from "@/hooks/useConversationFileSource";
import { conversationHasFileArtifacts } from "@/lib/conversationFileChanges";
import { resolveConversationLocalTarget } from "@/services/sidecarRouting";
import {
  useActiveMessageContent,
  useConversationStore,
} from "@/stores/conversation";
import { runtimeOf } from "@/stores/conversation/runtime";
import {
  type ExecutionRuntime,
  projectRuntime,
  useExecutionStore,
} from "@/stores/execution";
import {
  CHANGES_TAB_ID,
  COMMAND_TAB_ID,
  type DetailTab,
  TEAM_BROWSER_TAB_ID,
  TEAM_TERMINAL_TAB_ID,
  WORKSPACE_TAB_ID,
  terminalDismissKey,
  useSidePanelStore,
} from "@/stores/sidePanel";
import {
  countBusyPtySessions,
  useUserTerminalStore,
} from "@/stores/userTerminals";
import {
  Diff,
  FileText,
  FolderOpen,
  Gavel,
  MessageSquare,
  PanelRight,
  Plus,
  Radio,
  Sparkles,
  Terminal,
  UserRound,
  X,
} from "lucide-react";
import {
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * Live-check for content tabs. Run / content tabs need a loaded execution plan (and a
 * run tab additionally needs its run in the PROJECTED execution — §9.3). Simple-turn
 * Q&A tabs have no plan; terminal / file / browser tabs are session references and
 * stay live while open. Simple-turn stays live while the conversation holds the answer.
 */
function isDetailTabLive(
  byId: Record<string, ExecutionRuntime>,
  tab: DetailTab,
): boolean {
  if (
    tab.kind === "simple-turn" ||
    tab.kind === "terminal" ||
    tab.kind === "file" ||
    tab.kind === "browser"
  ) {
    return true;
  }
  const rt = byId[tab.messageId];
  if (!rt?.plan) return false;
  if (tab.kind !== "run") return true;
  return projectRuntime(rt)?.runs.some((r) => r.id === tab.runId) ?? false;
}

/**
 * The conversation's single right-docked surface (前端UX设计.md §十 · 方案 B):
 * `[工作区*] [改动?] | 内容 tabs | [+]`，画布态另出条件「指挥台」。
 * 「改动」有本对话 AI 文件改动（或深链）才挂，挂后不可关。
 */
export function SidePanel() {
  const open = useSidePanelStore((s) => s.open);
  const width = useSidePanelStore((s) => s.width);
  const setWidth = useSidePanelStore((s) => s.setWidth);
  const reclampWidth = useSidePanelStore((s) => s.reclampWidth);
  const cycleWidth = useSidePanelStore((s) => s.cycleWidth);
  const closePanel = useSidePanelStore((s) => s.closePanel);
  const tabs = useSidePanelStore((s) => s.tabs);
  const activeTabId = useSidePanelStore((s) => s.activeTabId);
  const setActiveTab = useSidePanelStore((s) => s.setActiveTab);
  const closeTab = useSidePanelStore((s) => s.closeTab);
  const openTerminalTab = useSidePanelStore((s) => s.openTerminalTab);
  const bindTerminalSession = useSidePanelStore((s) => s.bindTerminalSession);
  const openFileTab = useSidePanelStore((s) => s.openFileTab);
  const showBrowser = useSidePanelStore((s) => s.showBrowser);
  const changesFocusMessageId = useSidePanelStore(
    (s) => s.changesFocusMessageId,
  );
  const clearChangesFocus = useSidePanelStore((s) => s.clearChangesFocus);
  const currentConversationId = useConversationStore(
    (s) => s.currentConversationId,
  );
  const messages = useConversationStore(
    (s) => runtimeOf(s, currentConversationId).messages,
  );
  const spawnSession = useUserTerminalStore((s) => s.spawnSession);

  // 流式性能 (白屏卡死修复·Stage 3 收窄订阅): gate this dock on the SET of live tabs, not on
  // the whole `byId`. Subscribing to `byId` re-ran the panel (tab strip + RunDetailBody) on
  // every streaming token; RunDetailBody self-subscribes to its own slot, so the shell only
  // needs to know WHICH tabs stay valid — a key that changes only when that set does.
  const liveTabKey = useExecutionStore((s) =>
    tabs
      .filter((t) => isDetailTabLive(s.byId, t))
      .map((t) => t.id)
      .join("\u0001"),
  );
  // Boolean selector：byId 每 token 变，但 true/false 不变则不重渲顶栏；messages 变则换 selector。
  const hasFileChangesSelector = useCallback(
    (s: { byId: Record<string, ExecutionRuntime> }) =>
      conversationHasFileArtifacts(messages, s.byId),
    [messages],
  );
  const hasFileChanges = useExecutionStore(hasFileChangesSelector);
  const changesTabVisible = hasFileChanges || changesFocusMessageId != null;
  // 图上指挥 (前端UX设计.md §6.2): fixed 指挥台 tab + auto-surface (openPanel + badge,
  // never steals active tab). Hook runs before the `open` early-return so its effect
  // can reveal the panel even while closed. Inert in chat mode (`active` is false).
  const command = useCommandRegion();
  // 后台进程终端：活动出现时自动补一个 Terminal 内容 tab（不偷焦点），替代旧条件固定 tab。
  const terminal = useTerminalRegion();
  // 浏览器：活动出现时自动补一个 Browser 内容 tab（不偷焦点）。
  const browser = useBrowserRegion();

  const visibleTabs = useMemo(() => {
    const live = new Set(liveTabKey ? liveTabKey.split("\u0001") : []);
    return tabs.filter((t) => live.has(t.id));
  }, [tabs, liveTabKey]);
  const activeTab =
    activeTabId === WORKSPACE_TAB_ID ||
    activeTabId === CHANGES_TAB_ID ||
    activeTabId === COMMAND_TAB_ID
      ? null
      : (visibleTabs.find((t) => t.id === activeTabId) ?? null);
  const workspaceActive = activeTabId === WORKSPACE_TAB_ID;
  const changesActive = activeTabId === CHANGES_TAB_ID;
  const commandActive = command.show && activeTabId === COMMAND_TAB_ID;

  // Leaving canvas while on 指挥台: fall back to 工作区 (the tab disappears).
  useEffect(() => {
    if (!command.show && activeTabId === COMMAND_TAB_ID) {
      setActiveTab(WORKSPACE_TAB_ID);
    }
  }, [command.show, activeTabId, setActiveTab]);

  // 切对话：清深链聚焦；若仍停在「改动」且新对话无改动 → 由下方 effect 回工作区。
  // biome-ignore lint/correctness/useExhaustiveDependencies: currentConversationId is an intentional re-run key
  useEffect(() => {
    clearChangesFocus();
  }, [currentConversationId, clearChangesFocus]);

  // 「改动」不可见时若仍激活 → 回工作区。
  useEffect(() => {
    if (!changesTabVisible && activeTabId === CHANGES_TAB_ID) {
      setActiveTab(WORKSPACE_TAB_ID);
    }
  }, [changesTabVisible, activeTabId, setActiveTab]);

  // 终端「有活动」时自动补壳：用户关掉后记 dismiss，活动清零后才允许再次自动浮出。
  // 不含 canOpenPty——仅「能开 shell」不应强行挂 tab（否则关不掉）。
  useEffect(() => {
    const dismissKey = terminalDismissKey(currentConversationId);
    if (!terminal.show) {
      useSidePanelStore.getState().clearAutoSurfaceDismiss(dismissKey);
      return;
    }
    const sp = useSidePanelStore.getState();
    if (sp.isAutoSurfaceDismissed(dismissKey)) return;
    if (sp.tabs.some((t) => t.kind === "terminal")) return;
    openTerminalTab({ activate: false, reveal: false });
  }, [terminal.show, currentConversationId, openTerminalTab]);

  // 收敛历史多开终端顶栏 tab → 唯一壳（不激活、不强开）。
  useEffect(() => {
    const terminals = tabs.filter((t) => t.kind === "terminal");
    if (
      terminals.length <= 1 &&
      terminals.every((t) => t.id === TEAM_TERMINAL_TAB_ID)
    ) {
      return;
    }
    openTerminalTab({ activate: false, reveal: false });
  }, [tabs, openTerminalTab]);

  // 浏览器活动出现且尚无 browser 内容 tab → 自动补一个（不激活、不强开面板）。
  useEffect(() => {
    if (!browser.show) return;
    const hasBrowser = useSidePanelStore
      .getState()
      .tabs.some((t) => t.kind === "browser");
    if (hasBrowser) return;
    useSidePanelStore
      .getState()
      .openTab(
        { kind: "browser", id: TEAM_BROWSER_TAB_ID, title: "浏览器" },
        { activate: false, reveal: false },
      );
  }, [browser.show]);

  // Content / simple-turn tabs read message text via narrow slices so a streaming
  // turn (a new `messages` array every tick) never re-renders this dock (收窄订阅).
  const contentMessageId =
    activeTab?.kind === "content" ? activeTab.contentMessageId : null;
  const contentTabText = useActiveMessageContent(contentMessageId);
  const simplePromptId =
    activeTab?.kind === "simple-turn" ? activeTab.promptMessageId : null;
  const simpleAnswerId =
    activeTab?.kind === "simple-turn" ? activeTab.answerMessageId : null;
  const simplePromptText = useActiveMessageContent(simplePromptId);
  const simpleAnswerText = useActiveMessageContent(simpleAnswerId);

  const fileSource = useConversationFileSource(currentConversationId);

  // Pay for the workspace / changes bodies' first fetch only once shown; keep
  // mounted afterwards so switching back is instant and state survives.
  const [wsMounted, setWsMounted] = useState(false);
  const [changesMounted, setChangesMounted] = useState(false);
  useEffect(() => {
    if (open && workspaceActive) setWsMounted(true);
  }, [open, workspaceActive]);
  useEffect(() => {
    if (open && changesActive) setChangesMounted(true);
  }, [open, changesActive]);

  // Keep-alive keys for terminal / file bodies (mounted while tab exists).
  const terminalTabs = useMemo(
    () =>
      visibleTabs.filter(
        (t): t is Extract<DetailTab, { kind: "terminal" }> =>
          t.kind === "terminal",
      ),
    [visibleTabs],
  );
  const fileTabs = useMemo(
    () =>
      visibleTabs.filter(
        (t): t is Extract<DetailTab, { kind: "file" }> => t.kind === "file",
      ),
    [visibleTabs],
  );
  const browserTabs = useMemo(
    () => visibleTabs.filter((t) => t.kind === "browser"),
    [visibleTabs],
  );

  useEffect(() => {
    reclampWidth();
    const onResize = () => reclampWidth();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [reclampWidth]);

  const onResizeStart = (e: ReactPointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = width;
    const onMove = (ev: PointerEvent) =>
      setWidth(startWidth + (startX - ev.clientX));
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const onNewTerminal = useCallback(async () => {
    const tabId = openTerminalTab();
    if (!currentConversationId) return;
    const target = await resolveConversationLocalTarget(currentConversationId);
    if (!target) return;
    const result = await spawnSession({
      conversationId: currentConversationId,
      rootId: target.rootId,
      subpath: target.subpath,
    });
    if (result.ok) {
      bindTerminalSession(tabId, result.session_id);
    }
  }, [
    openTerminalTab,
    currentConversationId,
    spawnSession,
    bindTerminalSession,
  ]);

  const [terminalCloseBusyCount, setTerminalCloseBusyCount] = useState<
    number | null
  >(null);
  const [terminalCloseBusy, setTerminalCloseBusy] = useState(false);

  const finishCloseTerminalTab = useCallback(async () => {
    setTerminalCloseBusy(true);
    try {
      if (currentConversationId) {
        const ok = await useUserTerminalStore
          .getState()
          .killConversation(currentConversationId);
        if (!ok) return;
      }
      setTerminalCloseBusyCount(null);
      closeTab(TEAM_TERMINAL_TAB_ID);
    } finally {
      setTerminalCloseBusy(false);
    }
  }, [currentConversationId, closeTab]);

  const onCloseContentTab = useCallback(
    (tabId: string) => {
      if (tabId !== TEAM_TERMINAL_TAB_ID) {
        closeTab(tabId);
        return;
      }
      const sessions = currentConversationId
        ? useUserTerminalStore.getState().sessionsFor(currentConversationId)
        : [];
      const busyCount = countBusyPtySessions(sessions);
      if (busyCount > 0) {
        setTerminalCloseBusyCount(busyCount);
        return;
      }
      void finishCloseTerminalTab();
    },
    [closeTab, currentConversationId, finishCloseTerminalTab],
  );

  if (!open) return null;

  return (
    <aside
      className="relative flex shrink-0 flex-col border-l border-border bg-card"
      style={{ width }}
    >
      <Button
        variant="ghost"
        aria-label="拖拽调整面板宽度（双击在 最大/默认/最小 间复位）"
        onPointerDown={onResizeStart}
        onDoubleClick={cycleWidth}
        className="absolute left-0 top-0 z-10 h-full w-1 min-w-0 cursor-col-resize rounded-none bg-transparent p-0 hover:bg-primary/40"
      />

      <div className="flex h-11 shrink-0 items-center gap-1 border-b border-border px-2 py-1.5 pr-1">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          <FixedTab
            active={workspaceActive}
            onClick={() => setActiveTab(WORKSPACE_TAB_ID)}
            icon={<FolderOpen size={14} />}
            label="工作区"
          />
          {changesTabVisible && (
            <FixedTab
              active={changesActive}
              onClick={() => setActiveTab(CHANGES_TAB_ID)}
              icon={<Diff size={14} />}
              label="改动"
            />
          )}
          {command.show && (
            <CommandTab
              active={commandActive}
              badge={command.badge}
              onClick={() => setActiveTab(COMMAND_TAB_ID)}
            />
          )}
          <div className="mx-0.5 h-4 w-px shrink-0 bg-border" aria-hidden />
          {visibleTabs.map((tab) => (
            <ContentTabChip
              key={tab.id}
              tab={tab}
              active={tab.id === activeTab?.id}
              onSelect={() => setActiveTab(tab.id)}
              onClose={() => onCloseContentTab(tab.id)}
            />
          ))}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton aria-label="新建标签" title="新建标签">
              <Plus size={15} />
            </IconButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-36">
            <DropdownMenuItem onSelect={() => openFileTab()}>
              <FileText size={14} />
              文件
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void onNewTerminal()}>
              <Terminal size={14} />
              终端
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => showBrowser()}>
              <Radio size={14} />
              浏览器
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <SimpleTooltip label="隐藏侧面板 (Ctrl/Cmd+I)">
          <IconButton onClick={closePanel} aria-pressed aria-label="隐藏侧面板">
            <PanelRight size={15} />
          </IconButton>
        </SimpleTooltip>
      </div>

      <div className="relative min-h-0 flex-1">
        {wsMounted && (
          <div
            className={`absolute inset-0 ${workspaceActive ? "" : "hidden"}`}
          >
            <WorkspaceMode />
          </div>
        )}
        {changesMounted && changesTabVisible && (
          <div className={`absolute inset-0 ${changesActive ? "" : "hidden"}`}>
            <ConversationChangesPanel />
          </div>
        )}
        {command.show && (
          <div className={`absolute inset-0 ${commandActive ? "" : "hidden"}`}>
            <CommandPanelBody
              message={command.message}
              execution={command.execution}
              conversationId={command.conversationId}
              interactive={command.interactive}
            />
          </div>
        )}
        {terminalTabs.map((tab) => (
          <div
            key={tab.id}
            className={`absolute inset-0 ${
              activeTabId === tab.id ? "" : "hidden"
            }`}
          >
            <TerminalPanelBody preferredSessionId={tab.sessionId} />
          </div>
        ))}
        {fileTabs.map((tab) => (
          <div
            key={tab.id}
            className={`absolute inset-0 ${
              activeTabId === tab.id ? "" : "hidden"
            }`}
          >
            <FileTabBody
              path={tab.path}
              name={tab.name}
              source={fileSource}
              onClose={() => closeTab(tab.id)}
            />
          </div>
        ))}
        {browserTabs.map((tab) => {
          const active = activeTabId === tab.id;
          // 仅激活时挂载（切走即卸载 → 直播 SSE 随 BrowserLivePanel 断开）。
          if (!active) return null;
          return (
            <div key={tab.id} className="absolute inset-0">
              <BrowserPanel
                conversationId={browser.conversationId ?? currentConversationId}
                liveAvailable={browser.show}
              />
            </div>
          );
        })}
        {activeTab?.kind === "run" && (
          <div className="absolute inset-0 overflow-y-auto">
            <RunDetailBody
              key={`${activeTab.id}:${activeTab.runId}`}
              messageId={activeTab.messageId}
              runId={activeTab.runId}
            />
          </div>
        )}
        {activeTab?.kind === "content" && (
          <div className="absolute inset-0 overflow-y-auto p-4">
            <Markdown content={contentTabText} />
          </div>
        )}
        {activeTab?.kind === "simple-turn" && (
          <div className="absolute inset-0 overflow-y-auto p-4">
            <section className="space-y-2">
              <h3 className="text-xs font-medium text-muted-foreground">
                提问
              </h3>
              <Markdown content={simplePromptText || "（无提问）"} />
            </section>
            <section className="mt-6 space-y-2 border-t border-border pt-6">
              <h3 className="text-xs font-medium text-muted-foreground">
                回答
              </h3>
              <Markdown
                content={
                  simpleAnswerText ||
                  (simpleAnswerId ? "（生成中…）" : "（无回答）")
                }
              />
            </section>
          </div>
        )}
      </div>
      <KillPtyConfirmDialog
        open={terminalCloseBusyCount != null}
        onOpenChange={(next) => {
          if (!next && !terminalCloseBusy) setTerminalCloseBusyCount(null);
        }}
        description={
          terminalCloseBusyCount != null && terminalCloseBusyCount > 1
            ? `关闭将终止 ${terminalCloseBusyCount} 个会话中的进程`
            : "关闭将终止此终端中的进程"
        }
        busy={terminalCloseBusy}
        onConfirm={() => void finishCloseTerminalTab()}
      />
    </aside>
  );
}

function FileTabBody({
  path,
  name,
  source,
  onClose,
}: {
  path: string;
  name: string;
  source: ReturnType<typeof useConversationFileSource>;
  onClose: () => void;
}) {
  if (!path || !name) {
    return (
      <EmptyHint
        inline
        icon={<FileText size={26} className="text-muted-foreground/40" />}
        title="打开文件"
        hint="在「工作区」文件树中点击文件，或从产物卡打开——将在此显示为独立标签。"
      />
    );
  }
  if (!source) {
    return (
      <EmptyHint
        inline
        icon={<FileText size={26} className="text-muted-foreground/40" />}
        title={name}
        hint="当前会话尚无可用文件源。"
      />
    );
  }
  return (
    <FileDetail
      key={path}
      source={source}
      path={path}
      name={name}
      onClose={onClose}
    />
  );
}

function FixedTab({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      className={`shrink-0 gap-1.5 px-2.5 py-1 text-sm font-medium ${
        active
          ? "bg-accent text-foreground"
          : "text-muted-foreground hover:bg-accent/50"
      }`}
      icon={icon}
    >
      {label}
    </Button>
  );
}

/** Fixed 指挥台 tab (canvas mode only): badge when actionable work awaits. */
function CommandTab({
  active,
  badge,
  onClick,
}: {
  active: boolean;
  badge: number;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      className={`relative shrink-0 gap-1.5 px-2.5 py-1 text-sm font-medium ${
        active
          ? "bg-accent text-foreground"
          : "text-muted-foreground hover:bg-accent/50"
      }`}
      icon={<Gavel size={14} />}
    >
      指挥台
      {!active && badge > 0 && (
        <span className="ml-0.5 rounded-full bg-primary/15 px-1.5 py-0.5 text-xs font-medium text-primary">
          {badge > 9 ? "9+" : badge}
        </span>
      )}
    </Button>
  );
}

/** Closable content-tab chip (terminal / file / browser / run / endpoint / Q&A). */
export function RunTabChip({
  tab,
  active,
  onSelect,
  onClose,
}: {
  tab: DetailTab;
  active: boolean;
  onSelect: () => void;
  onClose: () => void;
}) {
  return (
    <ContentTabChip
      tab={tab}
      active={active}
      onSelect={onSelect}
      onClose={onClose}
    />
  );
}

function ContentTabChip({
  tab,
  active,
  onSelect,
  onClose,
}: {
  tab: DetailTab;
  active: boolean;
  onSelect: () => void;
  onClose: () => void;
}) {
  const icon =
    tab.kind === "content" ? (
      tab.endpoint === "prompt" ? (
        <UserRound size={14} className="shrink-0" />
      ) : (
        <Sparkles size={14} className="shrink-0" />
      )
    ) : tab.kind === "simple-turn" ? (
      <MessageSquare size={14} className="shrink-0" />
    ) : tab.kind === "terminal" ? (
      <Terminal size={14} className="shrink-0" />
    ) : tab.kind === "file" ? (
      <FileText size={14} className="shrink-0" />
    ) : tab.kind === "browser" ? (
      <Radio size={14} className="shrink-0" />
    ) : null;

  return (
    <div
      className={`group/tab flex shrink-0 items-center rounded-lg ${
        active
          ? "bg-accent text-foreground"
          : "text-muted-foreground hover:bg-accent/50"
      }`}
    >
      <Button
        variant="ghost"
        onClick={onSelect}
        icon={icon ?? undefined}
        className="h-auto max-w-[140px] truncate rounded-none py-1 pl-2.5 pr-1 text-sm font-normal"
      >
        {tab.title}
      </Button>
      <IconButton
        onClick={onClose}
        aria-label={`关闭 ${tab.title}`}
        className="mr-1 size-5 opacity-0 group-hover/tab:opacity-100"
      >
        <X size={12} />
      </IconButton>
    </div>
  );
}
