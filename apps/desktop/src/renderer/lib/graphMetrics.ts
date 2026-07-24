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
