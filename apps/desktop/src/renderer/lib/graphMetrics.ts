/**
 * Collaboration-graph node metrics — the single source for the fixed agent-node
 * footprint used by ELK layout, the first-paint bbox estimate, and the
 * structural band geometry (GraphScene). Kept in a dependency-free module so the
 * pure IR layer ({@link buildGraphScene}) can size bands without importing the
 * ELK engine (elkjs) via `@/lib/elk-layout`.
 *
 * `NODE_HEIGHT` is the **first-paint / cold** assumption only. After React Flow
 * measures real card heights, callers debounce-feed them into ELK `nodeSizes`
 * (secondary layout) so same-column peers keep a real gap when content grows.
 * Default is show-full on the graph — do not treat a fixed slot height as the
 * long-term sizing strategy.
 */
export const NODE_WIDTH = 210;
export const NODE_HEIGHT = 110;

/** Debounce before measured heights trigger a secondary ELK pass. */
export const HEIGHT_RELAYOUT_DEBOUNCE_MS = 160;

/** Ignore sub-pixel / 1px measure jitter when deciding whether to re-ELK. */
export const HEIGHT_RELAYOUT_EPS = 1;

export type NodeSizeEntry = { width: number; height: number };
export type NodeSizeMap = Record<string, NodeSizeEntry>;

/**
 * Build ELK `nodeSizes` from ids, optionally overlaying measured React Flow
 * heights. Missing / non-positive measurements keep {@link NODE_HEIGHT}.
 */
export function buildNodeSizeMap(
  nodeIds: readonly string[],
  measuredHeights?: Readonly<Record<string, number>>,
): NodeSizeMap {
  const out: NodeSizeMap = {};
  for (const id of nodeIds) {
    const m = measuredHeights?.[id];
    out[id] = {
      width: NODE_WIDTH,
      height: typeof m === "number" && m > 0 ? m : NODE_HEIGHT,
    };
  }
  return out;
}

/**
 * True when every positive measured height already matches `sizeMap` within
 * {@link HEIGHT_RELAYOUT_EPS} — the gate that prevents per-frame re-ELK.
 */
export function measuredHeightsMatchSizes(
  nodeIds: readonly string[],
  sizeMap: NodeSizeMap,
  measuredHeights: Readonly<Record<string, number>>,
  eps: number = HEIGHT_RELAYOUT_EPS,
): boolean {
  for (const id of nodeIds) {
    const m = measuredHeights[id];
    if (typeof m !== "number" || m <= 0) continue;
    const laid = sizeMap[id]?.height ?? NODE_HEIGHT;
    if (Math.abs(laid - m) > eps) return false;
  }
  return true;
}

/** Match `elk-layout` frame padding — keep graphMetrics elk-free. */
export const LAYOUT_PADDING = 24;

/**
 * Visual card height during the measure→secondary-ELK lag window:
 * `max(layoutSlotH, measuredH || slot)`. Fit-width / onMeasure must follow this
 * footprint (graphHost: shrink zoom to fit; never hide nodes via overflow).
 */
export function nodeVisualHeight(
  layoutSlotH: number,
  measuredH?: number | null,
): number {
  const slot = layoutSlotH > 0 ? layoutSlotH : NODE_HEIGHT;
  const m = typeof measuredH === "number" && measuredH > 0 ? measuredH : slot;
  return Math.max(slot, m);
}

/**
 * Soft-center Y — same formula as `projectFlowGraph.placed` / EmbeddedGraphCanvas.
 * Before secondary ELK, taller measured cards center in the cold layout slot.
 */
export function placedNodeY(
  slotY: number,
  layoutSlotH: number,
  measuredH?: number | null,
): number {
  if (typeof measuredH !== "number" || measuredH <= 0) return slotY;
  const layoutH = layoutSlotH > 0 ? layoutSlotH : NODE_HEIGHT;
  return slotY + (layoutH - measuredH) / 2;
}

export type VisualBbox = {
  width: number;
  height: number;
  /** World Y of the visual top when it spills above 0 (else 0). Fit viewport shifts by `-originY * zoom`. */
  originY: number;
};

/**
 * Current visual content AABB for embed fit-width — expands when measured height
 * exceeds the layout slot, without waiting for secondary ELK. Width/height never
 * fall below `layoutBbox`.
 */
export function computeVisualBbox(
  positions: Readonly<Record<string, { x: number; y: number }>>,
  nodeSizes: Readonly<Record<string, { width?: number; height?: number }>>,
  measuredHeights: Readonly<Record<string, number>>,
  layoutBbox: { width: number; height: number },
  padding: number = LAYOUT_PADDING,
): VisualBbox {
  let maxX = 0;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = 0;
  let any = false;
  for (const id of Object.keys(positions)) {
    const slot = positions[id];
    if (!slot) continue;
    any = true;
    const layoutH = nodeSizes[id]?.height ?? NODE_HEIGHT;
    const layoutW = nodeSizes[id]?.width ?? NODE_WIDTH;
    const measured = measuredHeights[id];
    const cardTop = placedNodeY(slot.y, layoutH, measured);
    const cardH =
      typeof measured === "number" && measured > 0 ? measured : layoutH;
    const extentTop = Math.min(slot.y, cardTop);
    const extentBottom = Math.max(slot.y + layoutH, cardTop + cardH);
    // extent span === nodeVisualHeight(layoutH, measured)
    minY = Math.min(minY, extentTop);
    maxY = Math.max(maxY, extentBottom);
    maxX = Math.max(maxX, slot.x + layoutW);
  }
  if (!any || !Number.isFinite(minY)) {
    return { width: layoutBbox.width, height: layoutBbox.height, originY: 0 };
  }
  const topOverhang = Math.max(0, -minY);
  const width = Math.max(layoutBbox.width, maxX + padding);
  const height = Math.max(layoutBbox.height, maxY + padding + topOverhang);
  return { width, height, originY: minY < 0 ? minY : 0 };
}
