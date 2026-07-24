/** Host-side layout helpers — AI produces structure, we compute positions (§七). */

import { cloneElement } from "./clone";
import { elementBox, unionBox } from "./geometry";
import type { SceneElement } from "./types";

export interface GridLayoutOptions {
  /** Max columns; defaults to ⌈√n⌉. */
  cols?: number;
  /** Gap between cells in world units. */
  gap?: number;
}

/** Arrange the selected elements in a left-to-right, top-to-bottom grid anchored at the
 * selection's current top-left. Sizes are preserved; only positions change. */
export function layoutGrid(
  elements: readonly SceneElement[],
  selected: ReadonlySet<string>,
  opts: GridLayoutOptions = {},
): SceneElement[] {
  const items = elements.filter((e) => selected.has(e.id));
  if (items.length < 2) return [...elements];

  const gap = opts.gap ?? 24;
  const cols = opts.cols ?? Math.ceil(Math.sqrt(items.length));
  const anchor = unionBox(items);
  if (!anchor) return [...elements];

  const sorted = [...items].sort((a, b) => {
    const ba = elementBox(a);
    const bb = elementBox(b);
    const rowA = Math.round(ba.y / 20);
    const rowB = Math.round(bb.y / 20);
    if (rowA !== rowB) return rowA - rowB;
    return ba.x - bb.x;
  });

  const colWidths: number[] = [];
  const rowHeights: number[] = [];
  for (let i = 0; i < sorted.length; i++) {
    const b = elementBox(sorted[i]);
    const col = i % cols;
    const row = Math.floor(i / cols);
    colWidths[col] = Math.max(colWidths[col] ?? 0, b.width);
    rowHeights[row] = Math.max(rowHeights[row] ?? 0, b.height);
  }

  const target = new Map<string, { x: number; y: number }>();
  let y = anchor.y;
  for (let row = 0; row < rowHeights.length; row++) {
    let x = anchor.x;
    for (let col = 0; col < cols; col++) {
      const idx = row * cols + col;
      if (idx >= sorted.length) break;
      target.set(sorted[idx].id, { x, y });
      x += (colWidths[col] ?? 0) + gap;
    }
    y += (rowHeights[row] ?? 0) + gap;
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
