/** DAG auto-layout for selected whiteboard elements (arrows = edges). */

import dagre from "@dagrejs/dagre";
import { cloneElement } from "./clone";
import { elementBox, unionBox } from "./geometry";
import type { SceneElement } from "./types";

export interface DagreLayoutOptions {
  /** Layout direction; default left-to-right. */
  rankdir?: "TB" | "LR";
  /** Node / rank separation in world units. */
  gap?: number;
}

/** Re-layout the selected non-arrow elements along their arrow edges using dagre.
 * Unselected elements and arrows bound into the set move with their endpoints. */
export function layoutDagre(
  elements: readonly SceneElement[],
  selected: ReadonlySet<string>,
  opts: DagreLayoutOptions = {},
): SceneElement[] {
  const nodes = elements.filter(
    (e) => selected.has(e.id) && e.type !== "arrow" && e.type !== "line",
  );
  if (nodes.length < 2) return [...elements];

  const nodeIds = new Set(nodes.map((n) => n.id));
  const g = new dagre.graphlib.Graph();
  const gap = opts.gap ?? 48;
  g.setGraph({
    rankdir: opts.rankdir ?? "LR",
    nodesep: gap,
    ranksep: gap + 16,
    marginx: 0,
    marginy: 0,
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const el of nodes) {
    const b = elementBox(el);
    g.setNode(el.id, {
      width: Math.max(b.width, 8),
      height: Math.max(b.height, 8),
    });
  }

  for (const el of elements) {
    if (el.type !== "arrow" && el.type !== "line") continue;
    const a = el.start?.id;
    const b = el.end?.id;
    if (a && b && nodeIds.has(a) && nodeIds.has(b)) {
      g.setEdge(a, b);
    }
  }

  dagre.layout(g);

  const anchor = unionBox(nodes);
  if (!anchor) return [...elements];

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  for (const id of nodeIds) {
    const n = g.node(id);
    if (!n) continue;
    minX = Math.min(minX, n.x - n.width / 2);
    minY = Math.min(minY, n.y - n.height / 2);
  }

  const target = new Map<string, { x: number; y: number }>();
  for (const el of nodes) {
    const n = g.node(el.id);
    if (!n) continue;
    target.set(el.id, {
      x: anchor.x + (n.x - n.width / 2) - minX,
      y: anchor.y + (n.y - n.height / 2) - minY,
    });
  }

  return elements.map((e) => {
    const t = target.get(e.id);
    if (!t) return e;
    const b = elementBox(e);
    const dx = t.x - b.x;
    const dy = t.y - b.y;
    if (dx === 0 && dy === 0) return e;
    const copy = cloneElement(e);
    copy.x += dx;
    copy.y += dy;
    if (copy.type === "arrow" && copy.points) {
      copy.points = copy.points.map(
        ([px, py]) => [px + dx, py + dy] as [number, number],
      );
    }
    return copy;
  });
}
