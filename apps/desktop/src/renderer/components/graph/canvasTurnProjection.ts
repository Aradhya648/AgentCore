/**
 * Canvas per-turn Document projection — shared {@link projectTurnGraph} with
 * `documentShell: true`. Live faces / inject paint self-subscribe; this only
 * emits structure + shell coordinates.
 */

import type { Execution } from "@/stores/execution";
import type { GraphLayout } from "@/stores/graph";
import type { CanvasTurnProjection } from "./canvasSpine";
import {
  graphDocumentFingerprint,
  graphShellSnapshotKey,
} from "./graphDocument";
import { projectTurnGraph } from "./projectTurnGraph";
import { type TurnLayoutSlice, expandedUnitsFromFold } from "./useGraphLayout";

export interface CanvasDocumentProjectionContext {
  collapsedSubtrees: ReadonlySet<string>;
  handleDirection: "horizontal" | "vertical";
  edgePathType: "smoothstep" | "bezier";
  layoutKind: GraphLayout;
  /** Per-turn act focus (undefined = follow live default). */
  actFocusByTurn: ReadonlyMap<string, string | null | undefined>;
}

/** Document gate key for one expanded turn (structure + shell coords). */
export function canvasTurnDocumentGateKey(
  turnId: string,
  execution: Execution,
  slice: TurnLayoutSlice,
  ctx: Pick<
    CanvasDocumentProjectionContext,
    "collapsedSubtrees" | "handleDirection" | "edgePathType" | "actFocusByTurn"
  >,
): string {
  if (!slice.layoutReady || !slice.bbox || !slice.scene)
    return `${turnId}:pending`;
  const expandedUnits = expandedUnitsFromFold(
    execution.runs,
    ctx.collapsedSubtrees,
  );
  const focusedActId = ctx.actFocusByTurn.get(turnId);
  const fp = graphDocumentFingerprint({
    execution,
    expandedUnits,
    focusedActId,
    handleDirection: ctx.handleDirection,
    edgePathType: ctx.edgePathType,
  });
  const shell = graphShellSnapshotKey({
    positions: slice.positions,
    groups: slice.groups,
    nodeSizes: slice.nodeSizes,
    actCards: slice.actCards,
    bbox: slice.bbox,
    edgeIds: slice.edges.map((e) => e.id),
  });
  return `${turnId}::${fp}::${shell}`;
}

/**
 * Project every ready expanded turn as Document shells.
 * Caller must gate with {@link canvasTurnDocumentGateKey} so streaming deltas
 * reuse prior Map entries / node refs.
 */
export function buildCanvasTurnProjections(
  expandedTurnInputs: { turnId: string; execution: Execution }[],
  turnLayouts: Record<string, TurnLayoutSlice>,
  ctx: CanvasDocumentProjectionContext,
  previous?: Map<string, CanvasTurnProjection>,
  previousGateKey?: string,
  nextGateKey?: string,
): Map<string, CanvasTurnProjection> {
  // Whole-canvas gate hit → reuse prior Map identity (stable RF child refs).
  if (
    previous &&
    previousGateKey != null &&
    nextGateKey != null &&
    previousGateKey === nextGateKey
  ) {
    return previous;
  }

  const out = new Map<string, CanvasTurnProjection>();
  for (const { turnId, execution } of expandedTurnInputs) {
    const slice = turnLayouts[turnId];
    if (!slice?.layoutReady || !slice.bbox || !slice.scene) continue;

    const gate = canvasTurnDocumentGateKey(turnId, execution, slice, ctx);
    const prev = previous?.get(turnId);
    if (prev && prev.documentGateKey === gate) {
      out.set(turnId, prev);
      continue;
    }

    const expandedUnits = expandedUnitsFromFold(
      execution.runs,
      ctx.collapsedSubtrees,
    );
    const captain = execution.runs.find((r) => r.kind === "captain") ?? null;
    const projected = projectTurnGraph({
      execution,
      scene: slice.scene,
      positions: slice.positions,
      nodeHeights: {},
      nodeSizes: slice.nodeSizes,
      groups: slice.groups,
      bbox: slice.bbox,
      actCards: slice.actCards,
      edges: slice.edges,
      handleDirection: ctx.handleDirection,
      edgePathType: ctx.edgePathType,
      litRunId: null,
      litEndpointMessageId: null,
      captainRun: captain,
      captainStatus: null,
      finalAnswer: null,
      captainSynthesisPreview: "",
      captainStatusCaption: null,
      taskMessage: null,
      activateNode: () => undefined,
      expandedUnits,
      onToggleUnitExpand: undefined,
      injectOverlay: null,
      layoutKind: ctx.layoutKind,
      onFocusAct: () => undefined,
      documentShell: true,
    });
    out.set(turnId, {
      layoutNodes: projected.nodes,
      edges: projected.edges,
      lanes: projected.lanes,
      debateStages: projected.debateStages,
      documentGateKey: gate,
      scene: slice.scene,
      captainRunId: captain?.id ?? null,
    });
  }
  return out;
}
