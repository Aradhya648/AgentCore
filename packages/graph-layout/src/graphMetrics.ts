/**
 * Collaboration-graph node metrics — the single source for the fixed agent-node
 * footprint used by ELK layout, fit bbox, and structural band geometry.
 * Dependency-free so hosts can size without importing the ELK engine.
 *
 * Whiteboard model: {@link NODE_WIDTH} / {@link NODE_HEIGHT} are the **layout
 * authority** for every agent slot.
 */
export const NODE_WIDTH = 210;
export const NODE_HEIGHT = 110;

export type NodeSizeEntry = { width: number; height: number };
export type NodeSizeMap = Record<string, NodeSizeEntry>;

/**
 * Build ELK `nodeSizes` for `nodeIds` — always the fixed layout footprint.
 * (Second arg kept optional for call-site compatibility; measurements are ignored.)
 */
export function buildNodeSizeMap(
  nodeIds: readonly string[],
  _measuredHeights?: Readonly<Record<string, number>>,
): NodeSizeMap {
  const out: NodeSizeMap = {};
  for (const id of nodeIds) {
    out[id] = { width: NODE_WIDTH, height: NODE_HEIGHT };
  }
  return out;
}

/** Match elk-layout frame padding — keep graphMetrics elk-free. */
export const LAYOUT_PADDING = 24;
