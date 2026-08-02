import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu";
import { useBackgroundTasksSync } from "@/stores/backgroundTasks";
import { useCommandPanelStore } from "@/stores/commandPanel";
import {
  useActiveGenerating,
  useConversationStore,
} from "@/stores/conversation";
import { ExecutionScopeContext, useActiveExecField } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { Background, Panel, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import type { EdgeTypes } from "@xyflow/react";
import { ArrowUp, Loader2, Network } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CanvasCommandBar } from "./CanvasCommandBar";
import { CanvasPlaybackControls } from "./CanvasPlaybackControls";
import { CanvasTurnRail } from "./CanvasTurnRail";
import { CanvasZoomControls } from "./CanvasZoomControls";
import { DebateStageBands } from "./DebateStageBands";
import { GraphActionBar } from "./GraphActionBar";
import { GraphContextMenu } from "./GraphContextMenu";
import { GraphLayoutError } from "./GraphLayoutError";
import { GraphToolbar } from "./GraphToolbar";
import { SimpleTurnNode } from "./SimpleTurnNode";
import { TurnGroupNode } from "./TurnGroupNode";
import { TurnSummaryNode } from "./TurnSummaryNode";
import { WaveLanes } from "./WaveLanes";
import {
  CanvasDocumentProviders,
  withCanvasEdgeTurnScope,
  withCanvasTurnScope,
} from "./canvasDocumentHost";
import {
  edgeTypes as dagEdgeTypes,
  nodeTypes as dagNodeTypes,
} from "./constants";
import { GraphHoverContext } from "./graphHover";
import { namespaceId, stripNamespace } from "./ids";
import type { GraphPendingDecision } from "./pendingDecisions";
import { useCanvasFlow } from "./useCanvasFlow";
import {
  useCanvasFocus,
  useCanvasFocusState,
  useCanvasNodeHandlers,
} from "./useCanvasFocus";
import { useCanvasTurns } from "./useCanvasTurns";
import { useGraphPendingDecisions } from "./useGraphPendingDecisions";

/**
 * 对话级画布 — single ReactFlow instance.
 *
 * LOD: folded turns = TurnSummaryNode / SimpleTurnNode; the focused team turn
 * expands IN PLACE as a compound TurnGroupNode whose children (AgentNode etc.)
 * share this same RF store via parentId + extent:"parent". No nested
 * ReactFlowProvider. Full-screen turn detail lives at
 * `#/conversations/:id/turn/:turnId` (Maximize / double-click navigate there).
 */

const canvasNodeTypes = {
  agent: withCanvasTurnScope(dagNodeTypes.agent),
  userInput: withCanvasTurnScope(dagNodeTypes.userInput),
  captain: withCanvasTurnScope(dagNodeTypes.captain),
  subTeamGroup: dagNodeTypes.subTeamGroup,
  actSummary: withCanvasTurnScope(dagNodeTypes.actSummary),
  turnGroup: TurnGroupNode,
  teamTurn: TurnSummaryNode,
  simpleTurn: SimpleTurnNode,
};

const canvasEdgeTypes = {
  step: withCanvasEdgeTurnScope(dagEdgeTypes.step),
} as EdgeTypes;

function ConversationCanvasInner() {
  const generating = useActiveGenerating();

  const { focusedTurn, setFocusedTurn } = useCanvasFocusState();

  const { turns, effectiveFocus, railItems } = useCanvasTurns({
    focusedTurn,
    setFocusedTurn,
  });

  const flow = useCanvasFlow({
    turns,
    effectiveFocus,
  });

  const {
    rfRef,
    canvasBoxRef,
    hasMoreBefore,
    loadingOlder,
    requestOlder,
    onMove,
    onInit,
  } = useCanvasFocus({
    turns,
    effectiveFocus,
    nodes: flow.nodes,
  });

  const showSimpleTurnDetail = useSidePanelStore((s) => s.showSimpleTurnDetail);
  const onSimpleTurnClick = useCallback(
    (turnId: string) => {
      const t = turns.find((x) => x.id === turnId && x.kind === "simple");
      if (!t) return;
      showSimpleTurnDetail(
        t.id,
        t.promptMessageId,
        t.answerMessageId,
        t.prompt || "对话",
      );
    },
    [turns, showSimpleTurnDetail],
  );

  const { onNodeClick, onNodeDoubleClick, makeOnRailSelect } =
    useCanvasNodeHandlers(setFocusedTurn, flow.onExpandTurn, onSimpleTurnClick);
  const onRailSelect = makeOnRailSelect(rfRef);

  const conversationId = useConversationStore((s) => s.currentConversationId);

  useBackgroundTasksSync(conversationId);
  useEffect(() => {
    const cmd = useCommandPanelStore.getState();
    cmd.setActive(true);
    return () => cmd.setActive(false);
  }, []);
  useEffect(() => {
    useCommandPanelStore.getState().setFocused(effectiveFocus);
  }, [effectiveFocus]);

  const [dispatched, setDispatched] = useState(false);
  useEffect(() => {
    if (!generating) setDispatched(false);
  }, [generating]);

  useEffect(() => () => useSidePanelStore.getState().closeContentTabs(), []);

  // #2: ignore turnGroup (compound parent) for hover; short debounce on leave
  // so parent→child transitions don't flash a false clear.
  const hoverClearRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const setHoveredNodeId = flow.setHoveredNodeId;
  const onNodeMouseEnter = useCallback(
    (_: React.MouseEvent, node: { id: string; type?: string }) => {
      if (node.type === "turnGroup" || node.type === "subTeamGroup") return;
      if (hoverClearRef.current != null) {
        clearTimeout(hoverClearRef.current);
        hoverClearRef.current = null;
      }
      setHoveredNodeId(node.id);
    },
    [setHoveredNodeId],
  );
  const onNodeMouseLeave = useCallback(
    (_: React.MouseEvent, node: { type?: string }) => {
      if (node.type === "turnGroup" || node.type === "subTeamGroup") return;
      if (hoverClearRef.current != null) clearTimeout(hoverClearRef.current);
      hoverClearRef.current = setTimeout(() => {
        setHoveredNodeId(null);
        hoverClearRef.current = null;
      }, 40);
    },
    [setHoveredNodeId],
  );
  useEffect(
    () => () => {
      if (hoverClearRef.current != null) clearTimeout(hoverClearRef.current);
    },
    [],
  );

  const activateCanvasNode = flow.activateCanvasNode;
  const handleKeyboardNav = flow.handleKeyboardNav;
  const onFlowNodeClick = useCallback(
    (event: React.MouseEvent, node: { id: string; type?: string }) => {
      if (
        node.type === "teamTurn" ||
        node.type === "simpleTurn" ||
        node.type === "turnGroup"
      ) {
        onNodeClick(event, node as never);
        return;
      }
      activateCanvasNode(node.id);
    },
    [onNodeClick, activateCanvasNode],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (
        e.key === "ArrowUp" ||
        e.key === "ArrowDown" ||
        e.key === "ArrowLeft" ||
        e.key === "ArrowRight" ||
        e.key === "Enter" ||
        e.key === "Escape"
      ) {
        if (handleKeyboardNav(e.key)) e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleKeyboardNav]);

  const setMenuNodeId = flow.setMenuNodeId;
  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: { id: string }) => {
      event.preventDefault();
      setMenuNodeId(node.id);
    },
    [setMenuNodeId],
  );

  const onPaneContextMenu = useCallback(
    (event: React.MouseEvent | MouseEvent) => {
      event.preventDefault();
      setMenuNodeId(null);
    },
    [setMenuNodeId],
  );

  const centerNode = useCallback(
    (id: string) => {
      const namespaced = effectiveFocus ? namespaceId(effectiveFocus, id) : id;
      rfRef.current?.fitView({
        nodes: [{ id: namespaced }, { id }],
        padding: 0.4,
        maxZoom: 1.2,
        duration: 300,
      });
    },
    [rfRef, effectiveFocus],
  );

  const fitViewAll = useCallback(() => {
    rfRef.current?.fitView({
      padding: 0.2,
      maxZoom: 1,
      duration: 300,
    });
  }, [rfRef]);

  const showGraphChrome = !!effectiveFocus && !!flow.focusedExec;

  // 图头行动条（R3）：聚合聚焦回合待拍板；点击定位（折叠幕内先聚焦幕，命名空间节点居中）。
  const pendingDecisions = useGraphPendingDecisions(
    flow.focusedExec,
    conversationId,
    effectiveFocus,
  );
  const [locateTarget, setLocateTarget] = useState<string | null>(null);
  const onLocateDecision = useCallback(
    (d: GraphPendingDecision) => {
      if (!d.runId) {
        fitViewAll();
        return;
      }
      if (d.actId && effectiveFocus)
        flow.focusActForTurn(effectiveFocus, d.actId);
      flow.activateCanvasNode(d.runId);
      setLocateTarget(d.runId);
    },
    [flow, effectiveFocus, fitViewAll],
  );
  useEffect(() => {
    if (!locateTarget) return;
    const namespaced = effectiveFocus
      ? namespaceId(effectiveFocus, locateTarget)
      : locateTarget;
    if (!flow.nodes.some((n) => n.id === namespaced)) return;
    const raf = requestAnimationFrame(() => centerNode(locateTarget));
    setLocateTarget(null);
    return () => cancelAnimationFrame(raf);
  }, [locateTarget, flow.nodes, effectiveFocus, centerNode]);
  useEffect(() => {
    if (!locateTarget) return;
    const t = window.setTimeout(() => setLocateTarget(null), 2500);
    return () => window.clearTimeout(t);
  }, [locateTarget]);

  const menuNodeBare =
    flow.menuNodeId != null ? stripNamespace(flow.menuNodeId) : null;

  const scopeBag = useMemo(
    () => ({
      projectedByTurn: flow.projectedByTurn,
      graphActionsForTurn: flow.graphActionsForTurn,
      fallbackActions: flow.graphActions,
    }),
    [flow.projectedByTurn, flow.graphActionsForTurn, flow.graphActions],
  );

  return (
    <ExecutionScopeContext.Provider value={effectiveFocus}>
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center border-b border-border pl-40 pr-12">
          <span className="truncate text-sm font-medium text-foreground">
            画布
          </span>
          {turns.length > 0 && (
            <span className="ml-2 shrink-0 text-xs text-muted-foreground">
              {turns.length} 回合
            </span>
          )}
        </div>
        <div ref={canvasBoxRef} className="relative min-h-0 flex-1">
          {turns.length > 0 ? (
            <ContextMenu>
              <ContextMenuTrigger asChild>
                <div className="relative h-full w-full">
                  <CanvasDocumentProviders
                    scopeBag={scopeBag}
                    injectPaint={flow.injectPaint}
                    finalAnswer={
                      flow.finalAnswer
                        ? { content: flow.finalAnswer.content }
                        : null
                    }
                  >
                    <GraphHoverContext.Provider value={flow.hoverState}>
                      <ReactFlow
                        nodes={flow.nodes}
                        edges={flow.edges}
                        nodeTypes={canvasNodeTypes}
                        edgeTypes={canvasEdgeTypes}
                        onInit={onInit}
                        onNodesChange={flow.onNodesChange}
                        onNodeClick={onFlowNodeClick}
                        onNodeDoubleClick={onNodeDoubleClick}
                        onNodeMouseEnter={onNodeMouseEnter}
                        onNodeMouseLeave={onNodeMouseLeave}
                        onNodeContextMenu={onNodeContextMenu}
                        onPaneContextMenu={onPaneContextMenu}
                        onMove={onMove}
                        nodesDraggable={false}
                        nodesConnectable={false}
                        nodesFocusable={false}
                        elementsSelectable={false}
                        zoomOnDoubleClick={false}
                        minZoom={0.15}
                        maxZoom={1.5}
                        proOptions={{ hideAttribution: true }}
                      >
                        <Background gap={20} size={1} />
                        {showGraphChrome && <WaveLanes waves={flow.waves} />}
                        {showGraphChrome && (
                          <DebateStageBands bands={flow.debateBands} />
                        )}
                        {hasMoreBefore && (
                          <Panel position="top-center">
                            <button
                              type="button"
                              onClick={requestOlder}
                              disabled={loadingOlder}
                              className="flex items-center gap-1.5 rounded-full border border-border bg-card/90 px-3 py-1 text-xs font-medium text-muted-foreground shadow-sm backdrop-blur transition-colors hover:text-foreground"
                            >
                              {loadingOlder ? (
                                <>
                                  <Loader2 size={12} className="animate-spin" />
                                  载入更早…
                                </>
                              ) : (
                                <>
                                  <ArrowUp size={12} />
                                  更早
                                </>
                              )}
                            </button>
                          </Panel>
                        )}
                        <Panel position="bottom-left">
                          <div className="flex flex-col gap-2">
                            {showGraphChrome && <PlaybackIfFrames />}
                            <CanvasZoomControls
                              onZoomIn={() =>
                                rfRef.current?.zoomIn({ duration: 200 })
                              }
                              onZoomOut={() =>
                                rfRef.current?.zoomOut({ duration: 200 })
                              }
                              onFit={fitViewAll}
                            />
                          </div>
                        </Panel>
                      </ReactFlow>
                    </GraphHoverContext.Provider>
                  </CanvasDocumentProviders>

                  {showGraphChrome && (
                    <GraphToolbar
                      layoutKind={flow.layoutKind}
                      onLayoutKindChange={flow.setLayoutKind}
                      metricsSummary={flow.metricsSummary}
                      injectFlowAvailable={flow.injectFlowAvailable}
                      showAuditInjectFlow={flow.showAuditInjectFlow}
                      onShowAuditInjectFlowChange={flow.setShowAuditInjectFlow}
                    />
                  )}

                  {showGraphChrome && (
                    <GraphActionBar
                      decisions={pendingDecisions}
                      onLocate={onLocateDecision}
                    />
                  )}

                  {showGraphChrome &&
                    flow.injectOverlay &&
                    (flow.showAuditInjectFlow ||
                      flow.injectOverlay.gapEdges.length > 0) && (
                      <div className="pointer-events-none absolute bottom-3 right-3 z-10 rounded-lg border border-border bg-card/90 px-2.5 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur">
                        <span className="text-foreground">──</span> 计划依赖
                        <span className="mx-2 text-muted-foreground/50">·</span>
                        <span className="text-primary">⇢</span> 数据注入（审计）
                      </div>
                    )}
                  {flow.layoutError && (
                    <div className="absolute inset-0 z-20 bg-background/85">
                      <GraphLayoutError detail={flow.layoutError} />
                    </div>
                  )}
                </div>
              </ContextMenuTrigger>
              <GraphContextMenu
                menuNodeId={menuNodeBare ?? null}
                captainRunId={flow.captainRun?.id}
                taskMessage={flow.taskMessage}
                finalAnswer={flow.finalAnswer}
                onNodeSelect={(runId) => activateCanvasNode(runId)}
                showRunDetailHere={flow.showRunDetailHere}
                activateNode={(id) => activateCanvasNode(id)}
                centerNode={centerNode}
                fitView={fitViewAll}
              />
            </ContextMenu>
          ) : (
            <div className="flex h-full items-center justify-center p-6">
              <div className="max-w-sm text-center">
                <Network
                  size={28}
                  className="mx-auto mb-3 text-muted-foreground"
                />
                <p className="text-sm text-muted-foreground">
                  还没有回合。用底部指令入口下达一个需要多 Agent 协作的任务，CEO
                  组好队后这里就会展开画布。
                </p>
              </div>
            </div>
          )}
          <CanvasTurnRail
            items={railItems}
            focusedId={effectiveFocus}
            onSelect={onRailSelect}
          />
          <CanvasCommandBar
            onDispatch={() => setDispatched(true)}
            waiting={dispatched && generating}
            allowBackground
            emptyConversation={turns.length === 0}
          />
        </div>
      </div>
    </ExecutionScopeContext.Provider>
  );
}

function PlaybackIfFrames({ autoPlay = false }: { autoPlay?: boolean }) {
  const hasFrames = useActiveExecField((rt) => rt.frames.length > 0);
  if (!hasFrames) return null;
  return <CanvasPlaybackControls autoPlay={autoPlay} />;
}

export function ConversationCanvas() {
  return (
    <ReactFlowProvider>
      <ConversationCanvasInner />
    </ReactFlowProvider>
  );
}
