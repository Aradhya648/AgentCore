/**
 * Canvas per-turn projection — runs the shared single-turn TeamGraph core
 * ({@link projectTurnGraph}) for every expanded turn, resolving each turn's
 * focus-conditional present state (lit / activate targets, CEO coordination-wait
 * & synthesis captions). Turn-local output; {@link buildTurnSpine} stacks it.
 */

import {
  captainSynthesisPreviewText,
  coordinationWaitCaptainCaption,
  waitingWorkerRoles,
} from "@/components/chat/teamSynthesisPhase";
import type { InjectGraphOverlay } from "@/lib/causalInject";
import type { Execution, ExecutionRuntime } from "@/stores/execution";
import type { GraphLayout } from "@/stores/graph";
import type { Node } from "@xyflow/react";
import type { CanvasTurnProjection } from "./canvasSpine";
import { deriveCaptainStatus } from "./helpers";
import { projectTurnGraph } from "./projectTurnGraph";
import { type TurnLayoutSlice, expandedUnitsFromFold } from "./useGraphLayout";

export interface CanvasProjectionContext {
  effectiveFocus: string | null;
  collapsedSubtrees: ReadonlySet<string>;
  execById: Record<string, ExecutionRuntime>;
  handleDirection: "horizontal" | "vertical";
  edgePathType: "smoothstep" | "bezier";
  cnyPerUsd: number;
  litRunId: string | null;
  litEndpointMessageId: string | null;
  finalAnswer: { id: string; content: string } | null;
  taskMessage: { id: string } | null;
  activateNode: (id: string) => void;
  onToggleUnitExpand: (unitId: string) => void;
  injectOverlay: InjectGraphOverlay | null;
  layoutKind: GraphLayout;
  focusActForTurn: (turnId: string, actId: string) => void;
}

/** Project every ready expanded turn's DAG turn-locally, keyed by turn id. */
export function buildCanvasTurnProjections(
  expandedTurnInputs: { turnId: string; execution: Execution }[],
  turnLayouts: Record<string, TurnLayoutSlice>,
  ctx: CanvasProjectionContext,
): Map<string, CanvasTurnProjection> {
  const out = new Map<string, CanvasTurnProjection>();
  for (const { turnId, execution } of expandedTurnInputs) {
    const slice = turnLayouts[turnId];
    if (!slice?.layoutReady || !slice.bbox || !slice.scene) continue;
    const expandedUnits = expandedUnitsFromFold(
      execution.runs,
      ctx.collapsedSubtrees,
    );
    const captain = execution.runs.find((r) => r.kind === "captain") ?? null;
    const capStatus = captain
      ? deriveCaptainStatus(execution, captain.id)
      : null;
    const isFocus = turnId === ctx.effectiveFocus;
    const focusAnswer = isFocus ? ctx.finalAnswer : null;
    const waitCaption = coordinationWaitCaptainCaption(
      ctx.execById[turnId]?.coordinationWait ?? null,
      { waitingRoles: waitingWorkerRoles(execution) },
    );
    const synthPreview =
      !focusAnswer && !waitCaption && capStatus === "running"
        ? captainSynthesisPreviewText(
            ctx.execById[turnId]?.teamSynthesisPreview ?? null,
          )
        : "";
    const projected = projectTurnGraph({
      execution,
      scene: slice.scene,
      positions: slice.positions,
      nodeHeights: slice.nodeHeights,
      nodeSizes: slice.nodeSizes,
      groups: slice.groups,
      bbox: slice.bbox,
      actCards: slice.actCards,
      edges: slice.edges,
      handleDirection: ctx.handleDirection,
      edgePathType: ctx.edgePathType,
      cnyPerUsd: ctx.cnyPerUsd,
      litRunId: isFocus ? ctx.litRunId : null,
      litEndpointMessageId: isFocus ? ctx.litEndpointMessageId : null,
      captainRun: captain,
      captainStatus: capStatus,
      finalAnswer: focusAnswer,
      captainSynthesisPreview: synthPreview,
      captainStatusCaption: waitCaption,
      taskMessage: isFocus ? ctx.taskMessage : null,
      activateNode: isFocus ? ctx.activateNode : () => undefined,
      expandedUnits,
      onToggleUnitExpand: ctx.onToggleUnitExpand,
      injectOverlay: isFocus ? ctx.injectOverlay : null,
      layoutKind: ctx.layoutKind,
      onFocusAct: (actId) => ctx.focusActForTurn(turnId, actId),
    });
    const present = new Map<string, Node["data"]>(
      projected.nodes.map((n) => [n.id, n.data]),
    );
    out.set(turnId, {
      layoutNodes: projected.nodes,
      presentData: present,
      edges: projected.edges,
      lanes: projected.lanes,
      debateStages: projected.debateStages,
    });
  }
  return out;
}
