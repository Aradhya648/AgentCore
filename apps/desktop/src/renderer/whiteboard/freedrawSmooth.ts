/** Hand-drawn stroke smoothing via perfect-freehand (§五.2 借库). */

import { getStroke } from "perfect-freehand";
import type { SceneElement } from "./types";
import { DEFAULT_STROKE_WIDTH } from "./types";

/** Replace a freedraw element's points with a smoothed outline polygon (relative to x/y)
 * and expand its bbox. No-op for very short strokes. */
export function smoothFreedraw(el: SceneElement): void {
  const pts = el.points ?? [];
  if (pts.length < 2) return;

  const abs = pts.map(([px, py]) => [el.x + px, el.y + py] as [number, number]);
  const size = (el.strokeWidth ?? DEFAULT_STROKE_WIDTH) * 2.5;
  const outline = getStroke(abs, {
    size,
    thinning: 0.6,
    smoothing: 0.55,
    streamline: 0.45,
    simulatePressure: true,
  });
  if (outline.length < 3) return;

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const [x, y] of outline) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }

  el.x = minX;
  el.y = minY;
  el.width = maxX - minX;
  el.height = maxY - minY;
  el.points = outline.map(([x, y]) => [x - minX, y - minY] as [number, number]);
}
