import { Markdown } from "@/components/chat/Markdown";
import { RunDetailBody } from "@/components/chat/detail/RunDetailBody";
import {
  CommandPanelBody,
  useCommandRegion,
} from "@/components/graph/CanvasDecisionPanel";
import {
  TerminalPanelBody,
  useTerminalRegion,
} from "@/components/terminal/TerminalPanel";
import { Button, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  BrowserLivePanel,
  useBrowserRegion,
} from "@/components/workspace/BrowserLivePanel";
import { EmbeddedPreview } from "@/components/workspace/EmbeddedPreview";
import { WorkspaceMode } from "@/components/workspace/WorkspacePanel";
import {
  useActiveMessageContent,
  useConversationStore,
} from "@/stores/conversation";
import {
  type ExecutionRuntime,
  projectRuntime,
  useExecutionStore,
} from "@/stores/execution";
import {
  BROWSER_TAB_ID,
  COMMAND_TAB_ID,
  type DetailTab,
  PREVIEW_TAB_ID,
  TERMINAL_TAB_ID,
  WORKSPACE_TAB_ID,
  useSidePanelStore,
} from "@/stores/sidePanel";
import {
  FolderOpen,
  Gavel,
  Globe,
  MessageSquare,
  Radio,
  Sparkles,
  Terminal,
  UserRound,
  X,
} from "lucide-react";
import {
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * Live-check for detail tabs. Run / content tabs need a loaded execution plan (and a
 * run tab additionally needs its run in the PROJECTED execution — §9.3). Simple-turn
 * Q&A tabs have no plan; they stay live while the conversation still holds the answer
 * message (validated at render via message content, not execution).
 */
function isDetailTabLive(
  byId: Record<string, ExecutionRuntime>,
  tab: DetailTab,
): boolean {
  if (tab.kind === "simple-turn") return true;
  const rt = byId[tab.messageId];
  if (!rt?.plan) return false;
  if (tab.kind !== "run") return true;
  return projectRuntime(rt)?.runs.some((r) => r.id === tab.runId) ?? false;
}

/**
 * The conversation's single right-docked surface (前端UX设计.md §十), modelled
 * as one flat tab strip: a fixed 「工作区」 home tab (files / snapshots /
 * handoff), then in canvas mode a fixed 「指挥台」 tab (boss decisions), followed
 * by closable run/content detail tabs. The workspace body is lazily mounted and
 * then kept alive (hidden, not unmounted) so its files aren't re-fetched when
 * toggling between it and a run.
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
  const previewTab = useSidePanelStore((s) => s.previewTab);
  const closePreview = useSidePanelStore((s) => s.closePreview);
  const currentConversationId = useConversationStore(
    (s) => s.currentConversationId,
  );
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
  // 图上指挥 (前端UX设计.md §6.2): fixed 指挥台 tab + auto-surface (openPanel + badge,
  // never steals active tab). Hook runs before the `open` early-return so its effect
  // can reveal the panel even while closed. Inert in chat mode (`active` is false).
  const command = useCommandRegion();
  // 后台进程终端 tab：有存活/曾有进程才出现；不绑画布模式。
  const terminal = useTerminalRegion();
  // L3 团队浏览器 tab：本会话曾用过浏览器才出现，之后常驻整场（同终端 tab 的条件常驻姿势）。
  const browser = useBrowserRegion();

  const visibleTabs = useMemo(() => {
    const live = new Set(liveTabKey ? liveTabKey.split("\u0001") : []);
    return tabs.filter((t) => live.has(t.id));
  }, [tabs, liveTabKey]);
  const activeTab =
    activeTabId === WORKSPACE_TAB_ID ||
    activeTabId === COMMAND_TAB_ID ||
    activeTabId === TERMINAL_TAB_ID ||
    activeTabId === PREVIEW_TAB_ID ||
    activeTabId === BROWSER_TAB_ID
      ? null
      : (visibleTabs.find((t) => t.id === activeTabId) ?? null);
  const workspaceActive = activeTabId === WORKSPACE_TAB_ID;
  const commandActive = command.show && activeTabId === COMMAND_TAB_ID;
  const terminalActive = terminal.show && activeTabId === TERMINAL_TAB_ID;
  const previewActive = previewTab !== null && activeTabId === PREVIEW_TAB_ID;
  const browserActive = browser.show && activeTabId === BROWSER_TAB_ID;

  // Leaving canvas while on 指挥台: fall back to 工作区 (the tab disappears).
  useEffect(() => {
    if (!command.show && activeTabId === COMMAND_TAB_ID) {
      setActiveTab(WORKSPACE_TAB_ID);
    }
  }, [command.show, activeTabId, setActiveTab]);

  // 终端 tab 消失时回落工作区。
  useEffect(() => {
    if (!terminal.show && activeTabId === TERMINAL_TAB_ID) {
      setActiveTab(WORKSPACE_TAB_ID);
    }
  }, [terminal.show, activeTabId, setActiveTab]);

  // 浏览器 tab 消失时（切到一个没用过浏览器的会话）回落工作区。tab 由会话内容派生，故
  // 「切换会话即收口」不需要另写一条 effect —— 换会话后 show 转 false 就走这里，SSE 连接
  // 随组件卸载自行断开。
  useEffect(() => {
    if (!browser.show && activeTabId === BROWSER_TAB_ID) {
      setActiveTab(WORKSPACE_TAB_ID);
    }
  }, [browser.show, activeTabId, setActiveTab]);

  // 切换会话 → 关闭内置浏览器预览（其内容属旧会话工作区，销毁原生视图 + 回落工作区）。
  useEffect(() => {
    if (previewTab && previewTab.conversationId !== currentConversationId) {
      closePreview();
    }
  }, [previewTab, currentConversationId, closePreview]);

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

  // Pay for the workspace body's first fetch only once it's actually shown; keep
  // it mounted afterwards so switching back is instant and state survives.
  const [wsMounted, setWsMounted] = useState(false);
  useEffect(() => {
    if (open && workspaceActive) setWsMounted(true);
  }, [open, workspaceActive]);

  // 面板宽度上限是「相对窗口」的动态值（sidePanelMaxWidth），窗口尺寸变化时把当前宽度
  // 收敛到新上限：大屏可拉宽、缩小窗口不会越界挤压主区。面板仅在 open 时渲染，故监听随
  // 组件挂载/卸载装拆；挂载时先跑一次，修正面板关闭期间发生的窗口变化。
  useEffect(() => {
    reclampWidth();
    const onResize = () => reclampWidth();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [reclampWidth]);

  // Drag the left edge to resize. Handwritten pointer tracking (no library);
  // setWidth clamps + persists, so the value is correct mid-drag and on release.
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

      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border pl-2 pr-1">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          <WorkspaceTab
            active={workspaceActive}
            onClick={() => setActiveTab(WORKSPACE_TAB_ID)}
          />
          {command.show && (
            <CommandTab
              active={commandActive}
              badge={command.badge}
              onClick={() => setActiveTab(COMMAND_TAB_ID)}
            />
          )}
          {terminal.show && (
            <TerminalTab
              active={terminalActive}
              onClick={() => setActiveTab(TERMINAL_TAB_ID)}
            />
          )}
          {previewTab && (
            <PreviewTab
              active={previewActive}
              onSelect={() => setActiveTab(PREVIEW_TAB_ID)}
              onClose={closePreview}
            />
          )}
          {browser.show && (
            <BrowserTab
              active={browserActive}
              onClick={() => setActiveTab(BROWSER_TAB_ID)}
            />
          )}
          {visibleTabs.map((tab) => (
            <RunTabChip
              key={tab.id}
              tab={tab}
              active={tab.id === activeTab?.id}
              onSelect={() => setActiveTab(tab.id)}
              onClose={() => closeTab(tab.id)}
            />
          ))}
        </div>
        <SimpleTooltip label="关闭面板 (Ctrl/Cmd+I)">
          <IconButton onClick={closePanel} aria-label="关闭面板">
            <X size={15} />
          </IconButton>
        </SimpleTooltip>
      </div>

      {/* Content area: 工作区 / 指挥台 / run·内容详情 — one active body at a time. */}
      <div className="relative min-h-0 flex-1">
        {wsMounted && (
          <div
            className={`absolute inset-0 ${workspaceActive ? "" : "hidden"}`}
          >
            <WorkspaceMode />
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
        {terminal.show && (
          <div className={`absolute inset-0 ${terminalActive ? "" : "hidden"}`}>
            <TerminalPanelBody />
          </div>
        )}
        {previewTab && (
          // 内置浏览器：保持挂载（非激活时 hidden），让切 tab 往返保留页面状态；EmbeddedPreview
          // 据 active 驱动原生视图显隐（遮挡管理）。
          <div className={`absolute inset-0 ${previewActive ? "" : "hidden"}`}>
            <EmbeddedPreview
              conversationId={previewTab.conversationId}
              path={previewTab.path}
              name={previewTab.name}
              active={previewActive}
            />
          </div>
        )}
        {browserActive && browser.conversationId && (
          // 浏览器：仅激活时挂载（切走即卸载 → SSE 断开 → 服务端停播，「无人看零开销」）——tab 常驻
          // 不等于正文常挂。key 绑会话，换会话即重建、重新附着。
          <div className="absolute inset-0">
            <BrowserLivePanel
              key={browser.conversationId}
              conversationId={browser.conversationId}
            />
          </div>
        )}
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
          // An endpoint bubble (提问 / 最终回答) surfaced from the canvas — the
          // deliverable read as plain Markdown, no run-detail chrome.
          <div className="absolute inset-0 overflow-y-auto p-4">
            <Markdown content={contentTabText} />
          </div>
        )}
        {activeTab?.kind === "simple-turn" && (
          // Canvas SimpleTurn light card: full Q&A (prompt + answer), no execution.
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
    </aside>
  );
}

/** The fixed home tab: always first, never closes. */
function WorkspaceTab({
  active,
  onClick,
}: {
  active: boolean;
  onClick: () => void;
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
      icon={<FolderOpen size={14} />}
    >
      工作区
    </Button>
  );
}

/** Fixed 指挥台 tab (canvas mode only): always second, never closes; badge when
 * there is actionable work the user hasn't switched over to see. */
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

/** Fixed 终端 tab：有后台进程才出现，不绑画布；永不关闭（随内容消失）。 */
function TerminalTab({
  active,
  onClick,
}: {
  active: boolean;
  onClick: () => void;
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
      icon={<Terminal size={14} />}
    >
      终端
    </Button>
  );
}

/** 内置浏览器「预览」tab chip：有预览目标才出现；可关闭（关闭即销毁原生视图）。 */
function PreviewTab({
  active,
  onSelect,
  onClose,
}: {
  active: boolean;
  onSelect: () => void;
  onClose: () => void;
}) {
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
        icon={<Globe size={14} />}
        className="h-auto rounded-none py-1 pl-2.5 pr-1 text-sm font-normal"
      >
        预览
      </Button>
      <IconButton
        onClick={onClose}
        aria-label="关闭预览"
        className="mr-1 size-5 opacity-0 group-hover/tab:opacity-100"
      >
        <X size={12} />
      </IconButton>
    </div>
  );
}

/**
 * L3 团队浏览器「浏览器」tab：本会话曾用过浏览器才出现，之后常驻整场、**不可关闭**（随会话切换
 * 消失，同「终端」tab）。刻意不叫「浏览器直播」——常驻后它在 turn 之间显示的是最后一帧 / 已结束
 * / 无直播占位，「直播」会变成不准的标签；与「预览」tab 的区分靠图标（Radio vs Globe）。
 */
function BrowserTab({
  active,
  onClick,
}: {
  active: boolean;
  onClick: () => void;
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
      icon={<Radio size={14} />}
    >
      浏览器
    </Button>
  );
}

/** A closable detail tab chip (a run's agent role, or an endpoint's 提问 /
 * 最终回答, + a close affordance). Shared by both detail-tab kinds; a content tab
 * carries an icon (matching its graph endpoint node) so it reads apart from the
 * icon-less run tabs at a glance. */
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
  // Content tabs mirror the graph bookends: 你的任务 (UserRound) / CEO 汇总 (Sparkles).
  // Simple-turn Q&A uses MessageSquare (same cue as the light card).
  const icon =
    tab.kind === "content" ? (
      tab.endpoint === "prompt" ? (
        <UserRound size={14} className="shrink-0" />
      ) : (
        <Sparkles size={14} className="shrink-0" />
      )
    ) : tab.kind === "simple-turn" ? (
      <MessageSquare size={14} className="shrink-0" />
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
