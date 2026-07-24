import { TurnCompare } from "@/components/chat/compare/TurnCompare";
import { DebateArena } from "@/components/chat/debate/arena/DebateArena";
import { GraphView } from "@/components/graph/GraphView";
import { defaultTurnDetailView } from "@/components/graph/planCapabilities";
import { SidePanel } from "@/components/layout/SidePanel";
import { Button, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  fetchMessageWindow,
  shouldSetGeneratingOnHydrate,
} from "@/services/messages";
import { loadRecovery } from "@/services/resume";
import { attachOnOpen, settleCloudRunningAssistant } from "@/services/turns";
import {
  getRuntime,
  useActiveMessages,
  useConversationStore,
} from "@/stores/conversation";
import {
  ExecutionScopeContext,
  hasRevisions,
  isDebate,
  useMessageExecution,
} from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import type { TurnDetailView } from "@/stores/ui";
import { ReactFlowProvider } from "@xyflow/react";
import {
  ArrowLeft,
  GitCompare,
  MessagesSquare,
  Network,
  PanelRight,
  Square,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

function parseView(raw: string | null): TurnDetailView | null {
  if (raw === "graph" || raw === "debate" || raw === "compare") return raw;
  return null;
}

/**
 * Full-screen turn detail — graph / debate / compare for one turn.
 * Pure deep-read / replay surface (前端UX设计.md §六); no conversation-level
 * composer. Live turns only expose a top-bar Stop for the turn being viewed.
 */
export function TurnDetailPage() {
  const { id: conversationId, turnId } = useParams<{
    id: string;
    turnId: string;
  }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const requestedView = parseView(searchParams.get("view"));
  const autoplay = searchParams.get("autoplay") === "1";
  const compareA = searchParams.get("a");
  const compareB = searchParams.get("b");
  const initialComparePair = useMemo<[string, string] | undefined>(() => {
    if (compareA && compareB) return [compareA, compareB];
    return undefined;
  }, [compareA, compareB]);

  // Ensure conversation data is loaded (same contract as ConversationPage).
  useEffect(() => {
    if (!conversationId) return;
    const store = useConversationStore.getState();
    if (conversationId !== store.currentConversationId) {
      store.switchConversation(conversationId);
    }
    const recoveryLoaded = loadRecovery(conversationId);
    let cancelled = false;
    void (async () => {
      try {
        const win = await fetchMessageWindow(conversationId);
        if (cancelled) return;
        const s = useConversationStore.getState();
        if (s.currentConversationId === conversationId) {
          const rt = getRuntime(conversationId);
          if (!(rt.isGenerating || rt.messages.length > 0)) {
            s.setMessageWindow(
              win.messages,
              {
                hasMoreBefore: win.hasMoreBefore,
                hasMoreAfter: win.hasMoreAfter,
              },
              conversationId,
            );
            s.setMemoryUpdates(win.memoryUpdates, conversationId);
            if (shouldSetGeneratingOnHydrate(win.messages)) {
              s.setGenerating(true, conversationId);
            }
            const last = win.messages.at(-1);
            if (last) {
              const recovery = await recoveryLoaded;
              if (cancelled) return;
              const canAttach =
                recovery.cloudLive && recovery.pausedCount === 0;
              if (last.role === "user" && canAttach) {
                void attachOnOpen(conversationId);
              } else if (
                last.role === "assistant" &&
                last.status === "running"
              ) {
                await settleCloudRunningAssistant(conversationId, recovery);
                if (cancelled) return;
              }
            }
          }
        }
      } catch {
        /* best-effort history load */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  const [scopeId, setScopeId] = useState(turnId ?? "");
  useEffect(() => {
    if (turnId) setScopeId(turnId);
  }, [turnId]);

  const execution = useMessageExecution(scopeId);
  const taskSummary = execution?.taskSummary;
  const messages = useActiveMessages();
  // Scoped to the turn being viewed — not "conversation is generating somewhere".
  const liveViewedTurn =
    messages.find((m) => m.id === scopeId)?.isStreaming ?? false;

  const debate = !!execution && isDebate(execution);
  // 对比 tab：按「是否存在可修订 run」判断，不按整图是否含辩论
  // （混合图幕 1 热修 + 幕 2 辩论时仍需对比入口）。
  const showCompare = !!execution && hasRevisions(execution);

  const view: TurnDetailView = useMemo(() => {
    if (requestedView === "compare" && showCompare) return "compare";
    if (requestedView === "debate" && debate) return "debate";
    if (requestedView === "graph") return "graph";
    return defaultTurnDetailView(execution, debate);
  }, [requestedView, debate, showCompare, execution]);

  const setView = useCallback(
    (next: TurnDetailView) => {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set("view", next);
          if (next !== "compare") {
            p.delete("a");
            p.delete("b");
          }
          return p;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const goBack = useCallback(() => {
    if (conversationId) navigate(`/conversations/${conversationId}`);
    else navigate(-1);
  }, [navigate, conversationId]);

  const stopGeneration = useCallback(() => {
    useConversationStore.getState().stopGeneration();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const sp = useSidePanelStore.getState();
      const panelVisible =
        sp.open &&
        sp.tabs.some((t) => t.id === sp.activeTabId && t.messageId === scopeId);
      if (panelVisible) sp.closePanel();
      else goBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goBack, scopeId]);

  useEffect(() => () => useSidePanelStore.getState().closeContentTabs(), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "i" || e.key === "I") {
        e.preventDefault();
        useSidePanelStore.getState().togglePanel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const panelOpen = useSidePanelStore((s) => s.open);
  const pendingBadge = useSidePanelStore((s) => s.pendingBadge);
  const togglePanel = useSidePanelStore((s) => s.togglePanel);

  if (!conversationId || !turnId) return null;

  return (
    <ExecutionScopeContext.Provider value={scopeId}>
      <div className="relative flex h-full min-h-0 flex-1 flex-col bg-background">
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4 pr-14">
          <Button
            variant="neutral"
            size="md"
            onClick={goBack}
            icon={<ArrowLeft size={16} />}
          >
            返回
          </Button>
          {taskSummary && (
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
              {taskSummary}
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {liveViewedTurn && (
              <Button
                variant="ghost"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                icon={<Square size={14} />}
                onClick={stopGeneration}
                aria-label="停止生成"
              >
                停止
              </Button>
            )}
            <div className="flex shrink-0 items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
              <Button
                variant="ghost"
                onClick={() => setView("graph")}
                aria-pressed={view === "graph"}
                icon={<Network size={14} />}
                className={
                  view === "graph"
                    ? "bg-accent text-foreground hover:bg-accent"
                    : undefined
                }
              >
                协作图
              </Button>
              {debate && (
                <Button
                  variant="ghost"
                  onClick={() => setView("debate")}
                  aria-pressed={view === "debate"}
                  icon={<MessagesSquare size={14} />}
                  className={
                    view === "debate"
                      ? "bg-accent text-foreground hover:bg-accent"
                      : undefined
                  }
                >
                  辩论室
                </Button>
              )}
              {showCompare && (
                <Button
                  variant="ghost"
                  onClick={() => setView("compare")}
                  aria-pressed={view === "compare"}
                  icon={<GitCompare size={14} />}
                  className={
                    view === "compare"
                      ? "bg-accent text-foreground hover:bg-accent"
                      : undefined
                  }
                >
                  对比
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Body row: the content column (graph/debate/compare) and the
            right-docked SidePanel sit side-by-side in a flex-ROW, so the panel
            docks to the side instead of falling to the bottom of the page column
            (mirrors AppShell/ConversationPage, where SidePanel is a flex-row
            sibling — it is built as a `shrink-0 flex-col border-l` right dock). */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
              {view === "graph" && (
                <div className="min-h-0 flex-1">
                  <ReactFlowProvider>
                    <GraphView interactive fitMode="view" autoplay={autoplay} />
                  </ReactFlowProvider>
                </div>
              )}
              {view === "debate" && debate && execution && (
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <DebateArena
                    execution={execution}
                    messageId={scopeId}
                    conversationId={conversationId}
                    interactive={liveViewedTurn}
                  />
                </div>
              )}
              {view === "compare" && showCompare && execution && (
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <div className="mx-auto max-w-5xl">
                    <TurnCompare
                      execution={execution}
                      messageId={scopeId}
                      initialPair={initialComparePair}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          <SidePanel />
        </div>

        <SimpleTooltip
          label={panelOpen ? "隐藏侧面板 (Ctrl/Cmd+I)" : "侧面板 (Ctrl/Cmd+I)"}
        >
          <div className="absolute right-3 top-2 z-20">
            <IconButton
              size="md"
              onClick={togglePanel}
              aria-pressed={panelOpen}
              aria-label={panelOpen ? "隐藏侧面板" : "侧面板"}
              className={`relative border border-border backdrop-blur ${
                panelOpen ? "bg-accent text-foreground" : "bg-card/80"
              }`}
            >
              <PanelRight size={16} />
              {!panelOpen && pendingBadge > 0 && (
                <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-xs font-medium text-primary-foreground">
                  {pendingBadge > 9 ? "9+" : pendingBadge}
                </span>
              )}
            </IconButton>
          </div>
        </SimpleTooltip>
      </div>
    </ExecutionScopeContext.Provider>
  );
}
