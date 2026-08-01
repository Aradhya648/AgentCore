import type { GraphLayout } from "@agentcore/graph-layout";

/** Dependency layouts (ELK). Same as {@link GraphLayout} after timeline removal. */
export type ElkGraphLayout = GraphLayout;

/** Pick the layout algorithm GraphView should actually run. */
export function resolveEffectiveGraphLayout(
  layoutKind: GraphLayout,
  _opts?: { interactive?: boolean; parallelAvailable?: boolean },
): GraphLayout {
  return layoutKind;
}
