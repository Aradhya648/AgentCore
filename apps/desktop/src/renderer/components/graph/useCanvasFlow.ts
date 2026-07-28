/**
 * Conversation-canvas flow: composes the shared single-turn TeamGraph core
 * ({@link projectTurnGraph} + morph / hover / keyboard hooks) across every
 * expanded turn, then stacks them into one ReactFlow store via the canvas spine
 * ({@link buildTurnSpine} et al). Only the multi-turn orchestration (fold state,
 * turn seeding, act focus per turn, spine composition) lives here now; the graph
 * rendering itself is the same core GraphView uses.
 */

import {
  hasParallelTimeline,
  parallelTimelineMetricsSummary,
} from "@/components/chat/ParallelTimeline";
import { useTurnAudit } from "@/hooks/useTurnAudit";
import { resolveEffectiveGraphLayout } from "@/lib/graph-layout-utils";
import { useConversationStore } from "@/stores/conversation";
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
import { useUsageStore } from "@/stores/usage";
import type { NodeChange } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  buildSpineEdges,
  buildTurnSpine,
  offsetBandsToGroup,
  patchSpineNodes,
  spineInvalidationKey,
  spineMorphSig,
} from "./canvasSpine";
import { buildCanvasTurnProjections } from "./canvasTurnProjection";
import { useGraphHoverState } from "./graphHover";
import { computeGraphFold } from "./helpers";
import { namespaceId, parseActCardId, parseNamespacedId } from "./ids";
import { executionGraphCapabilities } from "./planCapabilities";
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

  // Seed default expanded turns (newest first, cap 3) once per conversation.
  useEffect(() => {
    if (!conversationId) return;
    const teamIdsNewestFirst = [...turns]
      .reverse()
      .filter((t) => t.kind === "team")
      .map((t) => t.id);
    if (teamIdsNewestFirst.length === 0) return;
    ensureDefaultExpandedTurns(conversationId, teamIdsNewestFirst);
  }, [conversationId, turns, ensureDefaultExpandedTurns]);

  // When a brand-new latest team turn appears, expand it (LRU). Does not
  // re-expand a turn the user just collapsed.
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

  // 幕级 LOD（批 R2）：每回合的聚焦幕选择（UI 态）。undefined = 跟随实时默认
  // （进行中自动聚焦活跃幕、完成态整链折叠为卡）。点某幕卡 → 聚焦该幕。
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

  const expandedTurnInputs = useMemo(() => {
    const out: { turnId: string; execution: Execution }[] = [];
    for (const id of fold.expandedTurns) {
      const t = turns.find((x) => x.id === id);
      if (t?.kind === "team" && t.exec) {
        out.push({ turnId: id, execution: t.exec });
      }
    }
    return out;
  }, [fold.expandedTurns, turns]);

  // Seed newly discovered foldable parents as collapsed by default.
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

  const cnyPerUsd = useUsageStore((s) => s.cnyPerUsd);
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

  const execById = useExecutionStore((s) => s.byId);

  // 辩论回合最大化 → view=debate（与 StatusStrip「打开辩论室」/ 右坞深链一致）。
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

  // Project each expanded turn's DAG turn-locally via the shared core.
  const projectedByTurn = useMemo(
    () =>
      buildCanvasTurnProjections(expandedTurnInputs, turnLayouts, {
        effectiveFocus,
        collapsedSubtrees,
        execById,
        handleDirection,
        edgePathType,
        cnyPerUsd,
        litRunId,
        litEndpointMessageId,
        finalAnswer,
        taskMessage,
        activateNode,
        onToggleUnitExpand,
        injectOverlay,
        layoutKind: effectiveLayoutKind,
        focusActForTurn,
      }),
    [
      expandedTurnInputs,
      turnLayouts,
      collapsedSubtrees,
      handleDirection,
      edgePathType,
      cnyPerUsd,
      effectiveFocus,
      effectiveLayoutKind,
      litRunId,
      litEndpointMessageId,
      finalAnswer,
      taskMessage,
      activateNode,
      onToggleUnitExpand,
      injectOverlay,
      execById,
      focusActForTurn,
    ],
  );

  // Morph: brief CSS transition when any expanded turn's layout structure moves.
  const layoutSig = useMemo(
    () => spineMorphSig(expandedTurnInputs, turnLayouts),
    [expandedTurnInputs, turnLayouts],
  );
  const morphing = useLayoutMorph(layoutSig);

  // Activate a canvas node id (namespaced): act card → focus; non-focus turn →
  // open its run detail; focus turn → drill in.
  const activateCanvasNode = useCallback(
    (nodeId: string) => {
      if (turns.some((t) => t.id === nodeId)) return;
      const parsed = parseNamespacedId(nodeId);
      const turnId = parsed ? parsed.turnId : effectiveFocus;
      const raw = parsed ? parsed.bare : nodeId;
      // 幕摘要卡：点击聚焦该回合该幕（唯一聚焦幕），不走节点钻取。
      const actId = parseActCardId(raw);
      if (actId && turnId) {
        focusActForTurn(turnId, actId);
        return;
      }
      if (turnId && turnId !== effectiveFocus) {
        // Activate within non-focus expanded turn: open run detail there.
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

  // Keyboard navigation among agent nodes in the focused turn.
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
    () => patchSpineNodes(layoutNodes, turns, projectedByTurn),
    [layoutNodes, turns, projectedByTurn],
  );

  const edges = useMemo(
    () => buildSpineEdges(layoutEdges, projectedByTurn),
    [layoutEdges, projectedByTurn],
  );

  // Hover: inject keep-bright is namespaced to the focused turn's node ids.
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

  // Reset transient hover / menu / keyboard focus when the focus target changes.
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
  };
}
