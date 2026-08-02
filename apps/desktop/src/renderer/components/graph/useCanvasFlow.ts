/**
 * Conversation-canvas flow: Document shells per expanded turn (gated like GraphView)
 * stacked on the canvas spine; Live faces / inject paint self-subscribe.
 */

import {
  hasParallelTimeline,
  parallelTimelineMetricsSummary,
} from "@/components/chat/ParallelTimeline";
import { useTurnAudit } from "@/hooks/useTurnAudit";
import { resolveEffectiveGraphLayout } from "@/lib/graph-layout-utils";
import {
  isTerminalPhase,
  useActiveTurnPhase,
  useConversationStore,
} from "@/stores/conversation";
import {
  type Execution,
  isDebate,
  projectRuntime,
  useExecutionStore,
  useMessageExecution,
} from "@/stores/execution";
import { useConversationFold, useGraphStore } from "@/stores/graph";
import { type EndpointKind, useSidePanelStore } from "@/stores/sidePanel";
import { turnDetailPath } from "@/stores/ui";
import type { Edge, NodeChange } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useShallow } from "zustand/react/shallow";
import {
  type CanvasTurnProjection,
  buildSpineEdges,
  buildTurnSpine,
  offsetBandsToGroup,
  patchSpineNodes,
  spineInvalidationKey,
  spineMorphSig,
} from "./canvasSpine";
import {
  buildCanvasTurnProjections,
  canvasTurnDocumentGateKey,
} from "./canvasTurnProjection";
import type { GraphActionsValue } from "./graphActions";
import { useGraphHoverState } from "./graphHover";
import { type GraphInjectPaint, injectPaintFromOverlay } from "./graphLive";
import { computeGraphFold } from "./helpers";
import { namespaceId, parseActCardId, parseNamespacedId } from "./ids";
import { executionGraphCapabilities } from "./planCapabilities";
import { projectInjectGapEdges } from "./projectFlowGraph";
import type { TurnItem } from "./useCanvasTurns";
import { useGraphDrillIn } from "./useGraphDrillIn";
import { useGraphInjectFlow } from "./useGraphInjectFlow";
import { useGraphKeyboardNav } from "./useGraphKeyboardNav";
import { useMultiTurnLayouts } from "./useGraphLayout";
import { useLayoutMorph } from "./useLayoutMorph";

export interface UseCanvasFlowOptions {
  turns: TurnItem[];
  effectiveFocus: string | null;
}

export function useCanvasFlow({ turns, effectiveFocus }: UseCanvasFlowOptions) {
  const navigate = useNavigate();
  const focusedExec = useMessageExecution(effectiveFocus);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const turnPhase = useActiveTurnPhase();
  const turnTerminal = isTerminalPhase(turnPhase);
  const caps = executionGraphCapabilities(focusedExec);
  const { data: turnAudit } = useTurnAudit(
    caps.auditInject ? conversationId : null,
    caps.auditInject ? effectiveFocus : null,
  );

  const layoutKind = useGraphStore((s) => s.layoutKind);
  const setLayoutKind = useGraphStore((s) => s.setLayoutKind);
  const showAuditInjectFlow = useGraphStore((s) => s.showAuditInjectFlow);
  const setShowAuditInjectFlow = useGraphStore((s) => s.setShowAuditInjectFlow);
  const fold = useConversationFold(conversationId);
  const expandTurn = useGraphStore((s) => s.expandTurn);
  const collapseTurn = useGraphStore((s) => s.collapseTurn);
  const ensureDefaultExpandedTurns = useGraphStore(
    (s) => s.ensureDefaultExpandedTurns,
  );
  const ensureSubtreeDefaults = useGraphStore((s) => s.ensureSubtreeDefaults);
  const toggleSubtreeCollapsed = useGraphStore((s) => s.toggleSubtreeCollapsed);

  const parallelAvailable = !!focusedExec && hasParallelTimeline(focusedExec);
  const effectiveLayoutKind = resolveEffectiveGraphLayout(layoutKind);

  useEffect(() => {
    if (!conversationId) return;
    const teamIdsNewestFirst = [...turns]
      .reverse()
      .filter((t) => t.kind === "team")
      .map((t) => t.id);
    if (teamIdsNewestFirst.length === 0) return;
    ensureDefaultExpandedTurns(conversationId, teamIdsNewestFirst);
  }, [conversationId, turns, ensureDefaultExpandedTurns]);

  const lastAutoExpandedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!conversationId) return;
    let latest: string | null = null;
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].kind === "team") {
        latest = turns[i].id;
        break;
      }
    }
    if (!latest || lastAutoExpandedRef.current === latest) return;
    lastAutoExpandedRef.current = latest;
    expandTurn(conversationId, latest);
  }, [conversationId, turns, expandTurn]);

  const expandedTurnSet = useMemo(
    () => new Set(fold.expandedTurns),
    [fold.expandedTurns],
  );

  const collapsedSubtrees = useMemo(
    () => new Set(fold.collapsedSubtrees),
    [fold.collapsedSubtrees],
  );

  const [actFocusByTurn, setActFocusByTurn] = useState<
    Map<string, string | null | undefined>
  >(() => new Map());
  const focusActForTurn = useCallback((turnId: string, actId: string) => {
    setActFocusByTurn((prev) => {
      const next = new Map(prev);
      next.set(turnId, actId);
      return next;
    });
  }, []);

  // Expanded turns: subscribe each runtime by id (not whole byId table).
  const expandedTurnIds = fold.expandedTurns;
  const expandedRuntimes = useExecutionStore(
    useShallow((s) => expandedTurnIds.map((id) => s.byId[id])),
  );
  const expandedTurnInputs = useMemo(() => {
    const out: { turnId: string; execution: Execution }[] = [];
    const turnKind = new Map(turns.map((t) => [t.id, t]));
    expandedTurnIds.forEach((turnId, i) => {
      const rt = expandedRuntimes[i];
      const t = turnKind.get(turnId);
      if (t?.kind !== "team" || !rt) return;
      const execution = projectRuntime(rt);
      if (!execution) return;
      out.push({ turnId, execution });
    });
    return out;
  }, [expandedRuntimes, expandedTurnIds, turns]);

  useEffect(() => {
    if (!conversationId) return;
    for (const { execution } of expandedTurnInputs) {
      const captainId =
        execution.runs.find((r) => r.kind === "captain")?.id ?? null;
      const info = computeGraphFold(execution.runs, captainId);
      const parents = [...info.descendants.keys()].filter(
        (id) => !info.debateUnits.has(id),
      );
      if (parents.length > 0) ensureSubtreeDefaults(conversationId, parents);
    }
  }, [conversationId, expandedTurnInputs, ensureSubtreeDefaults]);

  const { layouts: turnLayouts, onNodesChange: onTurnNodesChange } =
    useMultiTurnLayouts(
      expandedTurnInputs,
      effectiveLayoutKind,
      collapsedSubtrees,
      "contain",
      actFocusByTurn,
    );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const byTurn = new Map<string, NodeChange[]>();
      for (const c of changes) {
        if (!("id" in c) || typeof c.id !== "string") continue;
        const parsed = parseNamespacedId(c.id);
        if (!parsed) continue;
        const list = byTurn.get(parsed.turnId) ?? [];
        list.push({ ...c, id: parsed.bare });
        byTurn.set(parsed.turnId, list);
      }
      for (const [turnId, list] of byTurn) {
        onTurnNodesChange(turnId, list);
      }
    },
    [onTurnNodesChange],
  );

  const onToggleUnitExpand = useCallback(
    (unitId: string) => {
      if (!conversationId) return;
      toggleSubtreeCollapsed(conversationId, unitId);
    },
    [conversationId, toggleSubtreeCollapsed],
  );

  const onCollapseTurn = useCallback(
    (turnId: string) => {
      if (!conversationId) return;
      collapseTurn(conversationId, turnId);
    },
    [conversationId, collapseTurn],
  );

  const onExpandTurn = useCallback(
    (turnId: string) => {
      if (!conversationId) return;
      expandTurn(conversationId, turnId);
    },
    [conversationId, expandTurn],
  );

  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  const showContentDetail = useSidePanelStore((s) => s.showContentDetail);

  const onNodeSelect = useCallback(
    (runId: string) => {
      if (!effectiveFocus || !focusedExec) return;
      const run = focusedExec.runs.find((r) => r.id === runId);
      const role = focusedExec.agents.find((a) => a.id === run?.agentId)?.role;
      showRunDetail(effectiveFocus, runId, role);
    },
    [effectiveFocus, focusedExec, showRunDetail],
  );

  const onEndpointSelect = useCallback(
    (contentMessageId: string, title: string, endpoint: EndpointKind) => {
      if (!effectiveFocus) return;
      showContentDetail(effectiveFocus, contentMessageId, title, endpoint);
    },
    [effectiveFocus, showContentDetail],
  );

  const {
    activateNode,
    showRunDetailHere,
    litRunId,
    litEndpointMessageId,
    finalAnswer,
    taskMessage,
    captainRun,
  } = useGraphDrillIn(focusedExec, {
    interactive: true,
    messageId: effectiveFocus,
    onNodeSelect,
    onEndpointSelect,
  });

  const handleDirection =
    effectiveLayoutKind === "leftright"
      ? ("horizontal" as const)
      : ("vertical" as const);
  const edgePathType =
    effectiveLayoutKind === "tree"
      ? ("bezier" as const)
      : ("smoothstep" as const);

  const focusedLayout =
    effectiveFocus && turnLayouts[effectiveFocus]
      ? turnLayouts[effectiveFocus]
      : null;

  const { injectOverlay, injectFlowAvailable } = useGraphInjectFlow({
    enabled: caps.auditInject,
    causalGraph: turnAudit?.causal_graph,
    edges: focusedLayout?.edges ?? null,
    litRunId,
    showAllInject: showAuditInjectFlow,
  });

  const metricsSummary = useMemo(
    () =>
      parallelAvailable && focusedExec
        ? parallelTimelineMetricsSummary(focusedExec)
        : null,
    [parallelAvailable, focusedExec],
  );

  const [menuNodeId, setMenuNodeId] = useState<string | null>(null);

  const maximizeTurn = useCallback(
    (turnId: string) => {
      if (!conversationId) return;
      const rt = useExecutionStore.getState().byId[turnId];
      const exec = rt ? projectRuntime(rt) : null;
      const view = exec && isDebate(exec) ? ("debate" as const) : undefined;
      navigate(turnDetailPath(conversationId, turnId, view));
    },
    [conversationId, navigate],
  );

  const projectionCtx = useMemo(
    () => ({
      collapsedSubtrees,
      handleDirection,
      edgePathType,
      layoutKind: effectiveLayoutKind,
      actFocusByTurn,
    }),
    [
      collapsedSubtrees,
      handleDirection,
      edgePathType,
      effectiveLayoutKind,
      actFocusByTurn,
    ],
  );

  // Document gate: only structure + shell coords — never streaming live fields.
  const documentGateKey = useMemo(
    () =>
      expandedTurnInputs
        .map(({ turnId, execution }) => {
          const slice = turnLayouts[turnId] ?? {
            layoutReady: false,
            bbox: null,
            scene: null,
            positions: {},
            groups: [],
            nodeSizes: {},
            actCards: [],
            edges: [],
          };
          return canvasTurnDocumentGateKey(
            turnId,
            execution,
            slice as (typeof turnLayouts)[string],
            projectionCtx,
          );
        })
        .join("||"),
    [expandedTurnInputs, turnLayouts, projectionCtx],
  );

  const projectedRef = useRef<Map<string, CanvasTurnProjection>>(new Map());
  const gateRef = useRef("");
  const inputsRef = useRef(expandedTurnInputs);
  inputsRef.current = expandedTurnInputs;
  const layoutsRef = useRef(turnLayouts);
  layoutsRef.current = turnLayouts;

  const projectedByTurn = useMemo(() => {
    const next = buildCanvasTurnProjections(
      inputsRef.current,
      layoutsRef.current,
      projectionCtx,
      projectedRef.current,
      gateRef.current,
      documentGateKey,
    );
    projectedRef.current = next;
    gateRef.current = documentGateKey;
    return next;
  }, [documentGateKey, projectionCtx]);

  const layoutSig = useMemo(
    () => spineMorphSig(expandedTurnInputs, turnLayouts),
    [expandedTurnInputs, turnLayouts],
  );
  const morphing = useLayoutMorph(layoutSig);

  const activateCanvasNode = useCallback(
    (nodeId: string) => {
      if (turns.some((t) => t.id === nodeId)) return;
      const parsed = parseNamespacedId(nodeId);
      const turnId = parsed ? parsed.turnId : effectiveFocus;
      const raw = parsed ? parsed.bare : nodeId;
      const actId = parseActCardId(raw);
      if (actId && turnId) {
        focusActForTurn(turnId, actId);
        return;
      }
      if (turnId && turnId !== effectiveFocus) {
        const t = turns.find((x) => x.id === turnId);
        if (t?.exec) {
          const run = t.exec.runs.find((r) => r.id === raw);
          const role = t.exec.agents.find((a) => a.id === run?.agentId)?.role;
          showRunDetail(turnId, raw, role);
        }
        return;
      }
      activateNode(raw);
    },
    [activateNode, turns, effectiveFocus, showRunDetail, focusActForTurn],
  );

  const navigableNodeIds = useMemo(() => {
    if (!effectiveFocus) return [] as string[];
    const proj = projectedByTurn.get(effectiveFocus);
    if (!proj) return [];
    return proj.layoutNodes
      .filter((n) => n.type === "agent")
      .map((n) => namespaceId(effectiveFocus, n.id));
  }, [effectiveFocus, projectedByTurn]);

  const { keyboardFocusId, setKeyboardFocusId, handleKeyboardNav } =
    useGraphKeyboardNav({
      navigableNodeIds,
      onActivate: activateCanvasNode,
    });

  const seenTurnsRef = useRef<Set<string>>(new Set());
  const firstSpineRef = useRef(true);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;

  const turnSpineKey = useMemo(() => spineInvalidationKey(turns), [turns]);

  const expandedKey = fold.expandedTurns.join(",");
  const projectedReadyKey = [...projectedByTurn.keys()].sort().join(",");

  // *Key strings force recompute when ref-backed turn data changes under stable deps.
  const { layoutNodes, layoutEdges, focusedGroupOrigin } =
    // biome-ignore lint/correctness/useExhaustiveDependencies: turnSpineKey/expandedKey/projectedReadyKey are intentional invalidation keys
    useMemo(() => {
      const spine = buildTurnSpine({
        turns: turnsRef.current,
        expandedTurnSet,
        projectedByTurn,
        turnLayouts,
        effectiveFocus,
        morphing,
        keyboardFocusId,
        seenTurns: seenTurnsRef.current,
        firstSpine: firstSpineRef.current,
        maximizeTurn,
        onCollapseTurn,
      });
      firstSpineRef.current = false;
      return spine;
    }, [
      turnSpineKey,
      expandedKey,
      projectedReadyKey,
      documentGateKey,
      effectiveFocus,
      projectedByTurn,
      turnLayouts,
      expandedTurnSet,
      maximizeTurn,
      onCollapseTurn,
      morphing,
      keyboardFocusId,
    ]);

  const nodes = useMemo(
    () => patchSpineNodes(layoutNodes, turns),
    [layoutNodes, turns],
  );

  // Document edges + Live inject gap overlay (namespaced; never runs ELK).
  const injectGapEdges = useMemo(() => {
    if (!effectiveFocus || !focusedLayout) return [] as Edge[];
    const bare = projectInjectGapEdges({
      injectOverlay,
      positions: focusedLayout.positions,
      nodeSizes: focusedLayout.nodeSizes,
      handleDirection,
      edgePathType,
    });
    return bare.map((e) => ({
      ...e,
      id: namespaceId(effectiveFocus, e.id),
      source: namespaceId(effectiveFocus, e.source),
      target: namespaceId(effectiveFocus, e.target),
    }));
  }, [
    effectiveFocus,
    focusedLayout,
    injectOverlay,
    handleDirection,
    edgePathType,
  ]);

  const edges = useMemo(() => {
    const doc = buildSpineEdges(layoutEdges, projectedByTurn);
    if (injectGapEdges.length === 0) return doc;
    return [...doc, ...injectGapEdges];
  }, [layoutEdges, projectedByTurn, injectGapEdges]);

  const injectPaint = useMemo((): GraphInjectPaint => {
    const paint = injectPaintFromOverlay(injectOverlay);
    if (!paint || !effectiveFocus) return paint;
    return {
      highlightEdgeIds: new Set(
        [...paint.highlightEdgeIds].map((id) =>
          namespaceId(effectiveFocus, id),
        ),
      ),
      focusedEdgeIds: new Set(
        [...paint.focusedEdgeIds].map((id) => namespaceId(effectiveFocus, id)),
      ),
      dimUnrelatedEdges: paint.dimUnrelatedEdges,
    };
  }, [injectOverlay, effectiveFocus]);

  const injectRelatedIds = useMemo(() => {
    const injectRelated = injectOverlay?.dimUnrelatedEdges
      ? injectOverlay.relatedNodeIds
      : null;
    if (!injectRelated || !effectiveFocus) return injectRelated;
    return new Set(
      [...injectRelated].flatMap((id) => [id, namespaceId(effectiveFocus, id)]),
    );
  }, [injectOverlay, effectiveFocus]);

  const { hoveredNodeId, setHoveredNodeId, hoverState } = useGraphHoverState({
    edges,
    injectRelatedIds,
  });

  const focusedProjection = effectiveFocus
    ? projectedByTurn.get(effectiveFocus)
    : undefined;
  const canvasActBands = useMemo(
    () =>
      offsetBandsToGroup(focusedProjection?.lanes ?? [], focusedGroupOrigin),
    [focusedProjection, focusedGroupOrigin],
  );
  const canvasDebateBands = useMemo(
    () =>
      offsetBandsToGroup(
        focusedProjection?.debateStages ?? [],
        focusedGroupOrigin,
      ),
    [focusedProjection, focusedGroupOrigin],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on focus change only
  useEffect(() => {
    setHoveredNodeId(null);
    setMenuNodeId(null);
    setKeyboardFocusId(null);
  }, [effectiveFocus]);

  const focusedSlice = effectiveFocus ? turnLayouts[effectiveFocus] : null;
  const layoutReady =
    !effectiveFocus || !focusedExec || (focusedSlice?.layoutReady ?? false);
  const layoutError = focusedSlice?.layoutError ?? null;

  const graphActions = useMemo<GraphActionsValue>(
    () => ({
      activateNode: activateCanvasNode,
      toggleUnitExpand: onToggleUnitExpand,
      focusAct: (actId: string) => {
        if (effectiveFocus) focusActForTurn(effectiveFocus, actId);
      },
      litRunId,
      litEndpointMessageId,
      taskMessageId: taskMessage?.id ?? null,
      finalAnswerId: finalAnswer?.id ?? null,
      turnTerminal,
    }),
    [
      activateCanvasNode,
      onToggleUnitExpand,
      effectiveFocus,
      focusActForTurn,
      litRunId,
      litEndpointMessageId,
      taskMessage?.id,
      finalAnswer?.id,
      turnTerminal,
    ],
  );

  /** Per-turn GraphActions — activate/focusAct namespaced to that turn. */
  const graphActionsForTurn = useCallback(
    (turnId: string): GraphActionsValue => ({
      activateNode: (id: string) => {
        const bare = parseNamespacedId(id)?.bare ?? id;
        activateCanvasNode(namespaceId(turnId, bare));
      },
      toggleUnitExpand: onToggleUnitExpand,
      focusAct: (actId: string) => focusActForTurn(turnId, actId),
      litRunId: turnId === effectiveFocus ? litRunId : null,
      litEndpointMessageId:
        turnId === effectiveFocus ? litEndpointMessageId : null,
      taskMessageId:
        turnId === effectiveFocus ? (taskMessage?.id ?? null) : null,
      finalAnswerId:
        turnId === effectiveFocus ? (finalAnswer?.id ?? null) : null,
      turnTerminal: turnId === effectiveFocus ? turnTerminal : false,
    }),
    [
      activateCanvasNode,
      onToggleUnitExpand,
      focusActForTurn,
      effectiveFocus,
      litRunId,
      litEndpointMessageId,
      taskMessage?.id,
      finalAnswer?.id,
      turnTerminal,
    ],
  );

  return {
    nodes,
    edges,
    layoutReady,
    layoutError,
    onNodesChange,
    focusedExec,
    effectiveLayoutKind,
    waves: canvasActBands,
    debateBands: canvasDebateBands,
    bbox: focusedSlice?.bbox ?? null,
    layoutKind,
    setLayoutKind,
    metricsSummary,
    injectFlowAvailable,
    showAuditInjectFlow,
    setShowAuditInjectFlow,
    injectOverlay,
    injectPaint,
    hoverState,
    hoveredNodeId,
    setHoveredNodeId,
    menuNodeId,
    setMenuNodeId,
    activateCanvasNode,
    showRunDetailHere,
    captainRun,
    finalAnswer,
    taskMessage,
    litRunId,
    onExpandTurn,
    onCollapseTurn,
    handleKeyboardNav,
    keyboardFocusId,
    focusActForTurn,
    graphActions,
    graphActionsForTurn,
    projectedByTurn,
    effectiveFocus,
  };
}
