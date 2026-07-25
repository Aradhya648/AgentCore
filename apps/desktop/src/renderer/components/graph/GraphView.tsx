import {
  hasParallelTimeline,
  parallelTimelineMetricsSummary,
} from "@/components/chat/ParallelTimeline";
import { captainSynthesisPreviewText } from "@/components/chat/teamSynthesisPhase";
import { useCoordinationWaitChrome } from "@/components/chat/useCoordinationWaitChrome";
import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu";
import { useTurnAudit } from "@/hooks/useTurnAudit";
import { resolveEffectiveGraphLayout } from "@/lib/graph-layout-utils";
import { computeVisualBbox } from "@/lib/graphMetrics";
import { isGraphTraceEnabled, traceGraphDomClip } from "@/services/graphTrace";
import { useConversationStore } from "@/stores/conversation";
import { useDisclosureStore } from "@/stores/disclosure";
import {
  type RunStatus,
  useActiveExecField,
  useExecutionScope,
  useProjectedExecution,
} from "@/stores/execution";
import { useGraphStore } from "@/stores/graph";
import type { EndpointKind } from "@/stores/sidePanel";
import { useUsageStore } from "@/stores/usage";
import { Background, type Node, ReactFlow } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CanvasPlaybackControls } from "./CanvasPlaybackControls";
import { CanvasZoomControls } from "./CanvasZoomControls";
import { DebateStageBands } from "./DebateStageBands";
import { GraphActionBar } from "./GraphActionBar";
import { GraphContextMenu } from "./GraphContextMenu";
import { GraphLayoutError } from "./GraphLayoutError";
import { GraphToolbar } from "./GraphToolbar";
import { WaveLanes } from "./WaveLanes";
import { edgeTypes, nodeTypes } from "./constants";
import { GraphFlowHost } from "./graphHost";
import { GraphHoverContext, useGraphHoverState } from "./graphHover";
import { deriveCaptainStatus } from "./helpers";
import type { GraphPendingDecision } from "./pendingDecisions";
import { executionGraphCapabilities } from "./planCapabilities";
import { projectTurnGraph } from "./projectTurnGraph";
import { buildGraphScene } from "./scene";
import { useActFocus } from "./useActFocus";
import { useGraphDrillIn } from "./useGraphDrillIn";
import { useGraphInjectFlow } from "./useGraphInjectFlow";
import { useGraphLayout } from "./useGraphLayout";
import { useGraphPendingDecisions } from "./useGraphPendingDecisions";
import { type GraphFitMode, useGraphViewport } from "./useGraphViewport";
import { positionsMorphSig, useLayoutMorph } from "./useLayoutMorph";

export type { GraphHoverState } from "./graphHover";
export { GraphHoverContext };

interface GraphViewProps {
  interactive?: boolean;
  fitMode?: GraphFitMode;
  onNodeSelect?: (runId: string) => void;
  onEndpointSelect?: (
    contentMessageId: string,
    title: string,
    endpoint: EndpointKind,
  ) => void;
  onMeasure?: (m: { height: number; overflowing: boolean }) => void;
  onClose?: () => void;
  autoplay?: boolean;
}

export function GraphView({
  interactive = true,
  fitMode = "view",
  onNodeSelect,
  onEndpointSelect,
  onMeasure,
  onClose,
  autoplay = false,
}: GraphViewProps = {}) {
  const messageId = useExecutionScope();
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const execution = useProjectedExecution();
  const caps = executionGraphCapabilities(execution);
  const { data: turnAudit } = useTurnAudit(
    caps.auditInject ? conversationId : null,
    caps.auditInject ? messageId : null,
  );
  const showAuditInjectFlow = useGraphStore((s) => s.showAuditInjectFlow);
  const setShowAuditInjectFlow = useGraphStore((s) => s.setShowAuditInjectFlow);
  const hasFrames = useActiveExecField((rt) => rt.frames.length > 0);
  const layoutKind = useGraphStore((s) => s.layoutKind);
  const setLayoutKind = useGraphStore((s) => s.setLayoutKind);
  const parallelAvailable = !!execution && hasParallelTimeline(execution);
  const effectiveLayoutKind = resolveEffectiveGraphLayout(layoutKind);
  // 内嵌模式：expandedUnits 按对话持久化（与画布 graph-fold 独立）。
  // 交互/全屏 GraphView 仍用会话内存态；画布多回合折叠走 graph store。
  const persistEmbedUnits = !interactive && !!messageId && !!conversationId;
  const embedUnitPrefix = persistEmbedUnits
    ? `${conversationId}::${messageId}:embed-unit:`
    : null;
  const setDisclosureKey = useDisclosureStore((s) => s.setKey);
  const embedUnitsFingerprint = useDisclosureStore((s) => {
    if (!embedUnitPrefix) return "";
    const ids: string[] = [];
    for (const [k, v] of Object.entries(s.map)) {
      if (v && k.startsWith(embedUnitPrefix)) {
        ids.push(k.slice(embedUnitPrefix.length));
      }
    }
    return ids.sort().join(",");
  });
  const [sessionExpandedUnits, setSessionExpandedUnits] = useState<Set<string>>(
    () => new Set(),
  );
  const expandedUnits = useMemo(() => {
    if (!embedUnitPrefix) return sessionExpandedUnits;
    if (!embedUnitsFingerprint) return new Set<string>();
    return new Set(embedUnitsFingerprint.split(","));
  }, [embedUnitPrefix, embedUnitsFingerprint, sessionExpandedUnits]);
  const onToggleUnitExpand = useCallback(
    (unitId: string) => {
      if (!embedUnitPrefix) {
        setSessionExpandedUnits((prev) => {
          const next = new Set(prev);
          if (next.has(unitId)) next.delete(unitId);
          else next.add(unitId);
          return next;
        });
        return;
      }
      const fullKey = `${embedUnitPrefix}${unitId}`;
      const cur = useDisclosureStore.getState().map[fullKey] ?? false;
      setDisclosureKey(fullKey, !cur, false);
    },
    [embedUnitPrefix, setDisclosureKey],
  );
  // 幕级 LOD（批 R2）：多幕回合聚焦态（进行中自动聚焦活跃幕，完成态整链折叠为卡）。
  // 单幕回合 focusScene.acts.length < 2，focusedActId 恒被 useGraphLayout 忽略。
  const focusScene = useMemo(
    () => (execution ? buildGraphScene(execution, { expandedUnits }) : null),
    [execution, expandedUnits],
  );
  const { focusedActId, focusAct, collapseActs } = useActFocus(
    focusScene,
    execution?.status,
  );
  const isMultiAct = (focusScene?.acts.length ?? 0) >= 2;
  const {
    positions,
    edges,
    bbox,
    layoutReady,
    layoutError,
    nodeHeights,
    nodeSizes,
    onNodesChange,
    groups,
    scene,
    actCards,
  } = useGraphLayout(
    execution,
    effectiveLayoutKind,
    fitMode,
    expandedUnits,
    focusedActId,
  );
  // fitMode=width: drive fit / onMeasure from current visual footprint (measured
  // heights) so the embed does not wait on secondary ELK — graphHost contract.
  const fitBbox = useMemo(() => {
    if (!bbox) return null;
    if (fitMode !== "width") return { ...bbox, originY: 0 };
    return computeVisualBbox(positions, nodeSizes, nodeHeights, bbox);
  }, [fitMode, bbox, positions, nodeSizes, nodeHeights]);
  const { containerRef, rfRef, overflowing, fitView, centerNode, onInit } =
    useGraphViewport({
      fitMode,
      bbox: fitBbox,
      originY: fitBbox?.originY ?? 0,
      layoutReady,
      onMeasure,
    });
  const handleDirection =
    effectiveLayoutKind === "leftright"
      ? ("horizontal" as const)
      : ("vertical" as const);
  const cnyPerUsd = useUsageStore((s) => s.cnyPerUsd);

  const {
    activateNode,
    showRunDetailHere,
    litRunId,
    litEndpointMessageId,
    finalAnswer,
    taskMessage,
    captainRun,
  } = useGraphDrillIn(execution, {
    interactive,
    messageId,
    onNodeSelect,
    onEndpointSelect,
    onClose,
  });

  // Audit inject flow (shared hook) over this turn's structural edges.
  const { injectOverlay, injectFlowAvailable } = useGraphInjectFlow({
    enabled: caps.auditInject,
    causalGraph: turnAudit?.causal_graph,
    edges,
    litRunId,
    showAllInject: showAuditInjectFlow,
  });

  // Hover (shared hook) — single-turn ids, no canvas namespacing.
  const injectRelatedIds = injectOverlay?.dimUnrelatedEdges
    ? injectOverlay.relatedNodeIds
    : null;
  const { setHoveredNodeId, hoverState } = useGraphHoverState({
    edges,
    injectRelatedIds,
  });

  const [menuNodeId, setMenuNodeId] = useState<string | null>(null);
  const metricsSummary = useMemo(
    () =>
      parallelAvailable && execution
        ? parallelTimelineMetricsSummary(execution)
        : null,
    [parallelAvailable, execution],
  );

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      // 幕摘要卡：点击聚焦该幕（展开为唯一聚焦幕），不走节点钻取。
      if (node.type === "actSummary") {
        const actId = (node.data as { actId?: string })?.actId;
        if (actId) focusAct(actId);
        return;
      }
      activateNode(node.id);
    },
    [activateNode, focusAct],
  );

  const onPaneClick = useCallback(() => {
    // 多幕：点空白折回整链幕摘要卡（R3 图头行动条前的轻量「缩回」手势）。
    if (isMultiAct && focusedActId) collapseActs();
  }, [isMultiAct, focusedActId, collapseActs]);

  // 图头行动条（R3）：聚合本回合待拍板；点击定位到对应节点。
  const pendingDecisions = useGraphPendingDecisions(
    execution,
    conversationId,
    messageId,
  );
  const [locateTarget, setLocateTarget] = useState<{
    runId: string;
    actId: string | null;
  } | null>(null);
  const onLocateDecision = useCallback(
    (d: GraphPendingDecision) => {
      if (!d.runId) {
        // execution 级且无代表节点（罕见）：退回整图 fit。
        fitView();
        return;
      }
      // 折叠幕内：先聚焦目标幕，聚焦幕 relayout 后再居中（下方 effect 承接）。
      if (isMultiAct && d.actId && d.actId !== focusedActId) focusAct(d.actId);
      activateNode(d.runId);
      // fit-width 内联态整图已尽收，居中无意义 → 仅高亮 + 开详情。
      if (fitMode !== "width")
        setLocateTarget({ runId: d.runId, actId: d.actId });
    },
    [isMultiAct, focusedActId, focusAct, activateNode, fitView, fitMode],
  );
  // 聚焦幕重排是异步的——等目标进 positions 再居中一次。
  useEffect(() => {
    if (!locateTarget || !layoutReady) return;
    if (!positions[locateTarget.runId]) return;
    const raf = requestAnimationFrame(() => centerNode(locateTarget.runId));
    setLocateTarget(null);
    return () => cancelAnimationFrame(raf);
  }, [locateTarget, layoutReady, positions, centerNode]);
  // 兜底：目标始终不定位（如折进子队的 run）时清除，避免悬挂。
  useEffect(() => {
    if (!locateTarget) return;
    const t = window.setTimeout(() => setLocateTarget(null), 2500);
    return () => window.clearTimeout(t);
  }, [locateTarget]);

  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node) => {
      event.preventDefault();
      setMenuNodeId(node.id);
    },
    [],
  );

  const hoverClearRef = useRef<number | null>(null);

  const onNodeMouseEnter = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (hoverClearRef.current != null) {
        cancelAnimationFrame(hoverClearRef.current);
        hoverClearRef.current = null;
      }
      setHoveredNodeId(node.id);
    },
    [setHoveredNodeId],
  );

  const onNodeMouseLeave = useCallback(() => {
    hoverClearRef.current = requestAnimationFrame(() => {
      setHoveredNodeId(null);
      hoverClearRef.current = null;
    });
  }, [setHoveredNodeId]);

  const onPaneContextMenu = useCallback(
    (event: React.MouseEvent | MouseEvent) => {
      event.preventDefault();
      setMenuNodeId(null);
    },
    [],
  );

  const captainStatus = useMemo<RunStatus | null>(
    () =>
      execution && captainRun
        ? deriveCaptainStatus(execution, captainRun.id)
        : null,
    [execution, captainRun],
  );

  const teamSynthesisPreview = useActiveExecField(
    (rt) => rt.teamSynthesisPreview,
  );
  const { captainCaption: captainWaitCaption } =
    useCoordinationWaitChrome(execution);
  const captainSynthesisPreview = useMemo(() => {
    if (finalAnswer || captainWaitCaption || captainStatus !== "running")
      return "";
    return captainSynthesisPreviewText(teamSynthesisPreview);
  }, [finalAnswer, captainWaitCaption, captainStatus, teamSynthesisPreview]);

  // Single-turn TeamGraph projection via the shared core (same one the canvas
  // uses per expanded turn). Host-specific: GraphView omits edgePathType so edges
  // stay smoothstep.
  const projected = useMemo(
    () =>
      execution && scene
        ? projectTurnGraph({
            execution,
            scene,
            positions,
            nodeHeights,
            nodeSizes,
            groups,
            bbox,
            actCards,
            edges,
            handleDirection,
            cnyPerUsd,
            litRunId,
            litEndpointMessageId,
            captainRun,
            captainStatus,
            finalAnswer,
            captainSynthesisPreview,
            captainStatusCaption: captainWaitCaption,
            taskMessage,
            activateNode,
            expandedUnits,
            onToggleUnitExpand,
            injectOverlay,
            layoutKind: effectiveLayoutKind,
            onFocusAct: focusAct,
          })
        : null,
    [
      execution,
      scene,
      positions,
      nodeHeights,
      nodeSizes,
      groups,
      bbox,
      actCards,
      edges,
      handleDirection,
      cnyPerUsd,
      litRunId,
      litEndpointMessageId,
      captainRun,
      captainStatus,
      finalAnswer,
      captainSynthesisPreview,
      captainWaitCaption,
      taskMessage,
      activateNode,
      expandedUnits,
      onToggleUnitExpand,
      injectOverlay,
      effectiveLayoutKind,
      focusAct,
    ],
  );

  // 结构换坐标时短暂 morph（与画布一致）；流式内容更新不改 positions → 不触发。
  const layoutSig = useMemo(
    () => (!layoutReady || !bbox ? "" : positionsMorphSig(positions)),
    [layoutReady, bbox, positions],
  );
  const morphing = useLayoutMorph(layoutSig);

  const flowNodes = useMemo(() => {
    const nodes = projected?.nodes ?? [];
    if (!morphing) return nodes;
    return nodes.map((n) => ({
      ...n,
      className: [n.className, "graph-layout-morphing"]
        .filter(Boolean)
        .join(" "),
    }));
  }, [projected, morphing]);

  // Dev：RF DOM 相对容器裁切采样（区分「投影丢」vs「看得见但被裁」）。
  useEffect(() => {
    if (!isGraphTraceEnabled() || !layoutReady || fitMode !== "width") return;
    const el = containerRef.current;
    if (!el) return;
    const raf = requestAnimationFrame(() => {
      const flow = el.querySelector(".react-flow");
      if (!flow) return;
      const c0 = flow.getBoundingClientRect();
      const nodes = [...el.querySelectorAll(".react-flow__node")].map(
        (nodeEl) => {
          const r = nodeEl.getBoundingClientRect();
          return {
            id: nodeEl.getAttribute("data-id") ?? "",
            top: r.top,
            bottom: r.bottom,
            left: r.left,
            right: r.right,
          };
        },
      );
      const clippedIds = nodes
        .filter((n) => n.id && n.top < c0.bottom && n.bottom > c0.bottom + 1)
        .map((n) => n.id);
      const fullyInsideCount = nodes.filter(
        (n) =>
          n.top >= c0.top &&
          n.bottom <= c0.bottom &&
          n.left >= c0.left &&
          n.right <= c0.right,
      ).length;
      if (clippedIds.length > 0) {
        traceGraphDomClip({
          rfNodeIds: nodes.map((n) => n.id).filter(Boolean),
          clippedIds,
          fullyInsideCount,
          containerH: Math.round(c0.height),
        });
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [containerRef.current, layoutReady, fitMode]);

  const flowEdges = projected?.edges ?? [];
  const laneBands = projected?.lanes ?? [];
  const debateBands = projected?.debateStages ?? [];

  const interactionProps = !interactive
    ? {
        zoomOnScroll: false,
        zoomOnPinch: false,
        zoomOnDoubleClick: false,
        panOnDrag: false,
        preventScrolling: false,
        minZoom: 0.05,
      }
    : {};

  if (!execution) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-muted-foreground">暂无执行任务</p>
          <p className="mt-1 text-xs text-muted-foreground">
            发送多 Agent 任务后，协作图将在此显示
          </p>
        </div>
      </div>
    );
  }

  return (
    <GraphFlowHost>
      <div className="flex h-full w-full flex-col">
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <div ref={containerRef} className="relative min-h-0 flex-1">
              {layoutError ? (
                <GraphLayoutError detail={layoutError} />
              ) : (
                layoutReady && (
                  <GraphHoverContext.Provider value={hoverState}>
                    <ReactFlow
                      nodes={flowNodes}
                      edges={flowEdges}
                      nodeTypes={nodeTypes}
                      edgeTypes={edgeTypes}
                      onInit={onInit}
                      onNodesChange={onNodesChange}
                      onNodeClick={onNodeClick}
                      onNodeMouseEnter={onNodeMouseEnter}
                      onNodeMouseLeave={onNodeMouseLeave}
                      onNodeContextMenu={onNodeContextMenu}
                      onPaneContextMenu={onPaneContextMenu}
                      onPaneClick={onPaneClick}
                      fitView={fitMode === "view"}
                      nodesDraggable={false}
                      nodesConnectable={false}
                      nodesFocusable={false}
                      elementsSelectable={false}
                      proOptions={{ hideAttribution: true }}
                      {...interactionProps}
                    >
                      <Background gap={20} size={1} />
                      <WaveLanes waves={laneBands} />
                      <DebateStageBands bands={debateBands} />
                    </ReactFlow>
                  </GraphHoverContext.Provider>
                )
              )}

              {fitMode === "width" && overflowing && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-card to-transparent" />
              )}

              {interactive && (
                <GraphToolbar
                  layoutKind={layoutKind}
                  onLayoutKindChange={setLayoutKind}
                  metricsSummary={metricsSummary}
                  injectFlowAvailable={injectFlowAvailable}
                  showAuditInjectFlow={showAuditInjectFlow}
                  onShowAuditInjectFlowChange={setShowAuditInjectFlow}
                />
              )}

              {/* 图头行动条：三宿主同挂，非交互内联态也显（导航不依赖 pan/zoom）。 */}
              {layoutReady && !layoutError && (
                <GraphActionBar
                  decisions={pendingDecisions}
                  onLocate={onLocateDecision}
                />
              )}

              {interactive &&
                injectOverlay &&
                (showAuditInjectFlow || injectOverlay.gapEdges.length > 0) && (
                  <div className="pointer-events-none absolute bottom-3 right-3 z-10 rounded-lg border border-border bg-card/90 px-2.5 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur">
                    <span className="text-foreground">──</span> 计划依赖
                    <span className="mx-2 text-muted-foreground/50">·</span>
                    <span className="text-primary">⇢</span> 数据注入（审计）
                  </div>
                )}

              {interactive && (
                <div className="absolute bottom-3 left-3 z-10 flex flex-col gap-2">
                  {hasFrames && <CanvasPlaybackControls autoPlay={autoplay} />}
                  <CanvasZoomControls
                    onZoomIn={() => rfRef.current?.zoomIn({ duration: 200 })}
                    onZoomOut={() => rfRef.current?.zoomOut({ duration: 200 })}
                    onFit={fitView}
                    fitLabel="适应画布 (F)"
                  />
                </div>
              )}
            </div>
          </ContextMenuTrigger>

          <GraphContextMenu
            menuNodeId={menuNodeId}
            captainRunId={captainRun?.id}
            taskMessage={taskMessage}
            finalAnswer={finalAnswer}
            onNodeSelect={onNodeSelect}
            showRunDetailHere={showRunDetailHere}
            onClose={onClose}
            activateNode={activateNode}
            centerNode={centerNode}
            fitView={fitView}
          />
        </ContextMenu>
      </div>
    </GraphFlowHost>
  );
}
