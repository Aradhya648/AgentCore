import { useNodeId } from "@xyflow/react";
import { createContext, useContext, useMemo, useState } from "react";

/** Pane-level hover / dim signal — paint only; never RF node.className. */
export type GraphHoverState = {
  hoveredNodeId: string | null;
  /**
   * When non-null, nodes whose id is not in this set should paint dimmed.
   * Combines hover-path highlight and optional inject-related keep-bright.
   */
  keepBrightIds: Set<string> | null;
};

export const GraphHoverContext = createContext<GraphHoverState>({
  hoveredNodeId: null,
  keepBrightIds: null,
});

/**
 * Hovered node plus every ancestor and descendant along directed edges
 * (full upstream + downstream path, not just 1-hop neighbors).
 */
export function hoverRelatedIds(
  hoveredNodeId: string | null,
  edges: { source: string; target: string }[],
): Set<string> | null {
  if (!hoveredNodeId) return null;

  const upstream = new Map<string, string[]>();
  const downstream = new Map<string, string[]>();
  for (const e of edges) {
    const ups = upstream.get(e.target);
    if (ups) ups.push(e.source);
    else upstream.set(e.target, [e.source]);
    const downs = downstream.get(e.source);
    if (downs) downs.push(e.target);
    else downstream.set(e.source, [e.target]);
  }

  const related = new Set([hoveredNodeId]);

  const walk = (adj: Map<string, string[]>) => {
    const stack = [hoveredNodeId];
    while (stack.length > 0) {
      const cur = stack.pop();
      if (cur === undefined) break;
      for (const next of adj.get(cur) ?? []) {
        if (related.has(next)) continue;
        related.add(next);
        stack.push(next);
      }
    }
  };

  walk(upstream);
  walk(downstream);
  return related;
}

/**
 * Intersection of active dim constraints. Null = no dimming.
 * A node stays bright only if it passes every active constraint.
 */
export function computeKeepBrightIds(
  hoverRelated: Set<string> | null,
  injectRelated: Set<string> | null,
): Set<string> | null {
  if (!hoverRelated && !injectRelated) return null;
  if (hoverRelated && injectRelated) {
    const out = new Set<string>();
    for (const id of hoverRelated) {
      if (injectRelated.has(id)) out.add(id);
    }
    return out;
  }
  return hoverRelated ?? injectRelated;
}

/**
 * Own the hovered-node state and derive the pane-level {@link GraphHoverState}
 * (hover-path highlight ∩ inject keep-bright) — the single hover implementation
 * shared by every host. Callers pass the already-namespaced inject set (canvas
 * namespaces per turn; GraphView passes raw ids) plus the edge list to walk.
 */
export function useGraphHoverState({
  edges,
  injectRelatedIds,
}: {
  edges: { source: string; target: string }[];
  injectRelatedIds: Set<string> | null;
}): {
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
  hoverState: GraphHoverState;
} {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const hoverState = useMemo<GraphHoverState>(() => {
    const hoverRelated = hoveredNodeId
      ? hoverRelatedIds(hoveredNodeId, edges)
      : null;
    return {
      hoveredNodeId,
      keepBrightIds: computeKeepBrightIds(hoverRelated, injectRelatedIds),
    };
  }, [hoveredNodeId, edges, injectRelatedIds]);
  return { hoveredNodeId, setHoveredNodeId, hoverState };
}

/** True when this RF node should paint at dim opacity (face/overlay only). */
export function useGraphNodeDimmed(): boolean {
  const nodeId = useNodeId();
  const { keepBrightIds } = useContext(GraphHoverContext);
  if (!keepBrightIds || nodeId == null) return false;
  return !keepBrightIds.has(nodeId);
}

/** Paint-layer dim classes — opacity only, no layout. */
export function graphNodeDimClass(dimmed: boolean): string {
  return dimmed
    ? "opacity-50 transition-opacity duration-150"
    : "opacity-100 transition-opacity duration-150";
}
