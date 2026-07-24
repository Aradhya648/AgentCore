/**
 * Pure drag-gesture geometry for the whiteboard engine (AI协作白板.md §六 自研引擎架构).
 *
 * Stateless helpers lifted out of {@link WhiteboardEngine}'s onPointerMove: the rubber-band box
 * shared by marquee-select and drag-create (plus its 1:1 square-lock variant), and the moving
 * endpoint of an arrow/line drag (with an optional 45° angle snap). Same nature as the sibling
 * pure modules (transform / snap / layout) — the engine owns the scene + pointer state and only
 * calls these; nothing here touches engine state.
 */

import type { Box } from "./geometry";

/** Axis-aligned box spanned by two corners (min corner + absolute extent). The rubber band for
 * marquee-select and the live bounds while drag-creating a shape both reduce to this. */
export function dragBox(ox: number, oy: number, wx: number, wy: number): Box {
  return {
    x: Math.min(ox, wx),
    y: Math.min(oy, wy),
    width: Math.abs(wx - ox),
    height: Math.abs(wy - oy),
  };
}

/** Like {@link dragBox} but locked to a 1:1 square (Shift while creating): the square grows from
 * the origin corner toward the cursor's quadrant, sized by the larger of |dx| / |dy|. A zero
 * delta on an axis falls back to the positive direction (matches `Math.sign(0 || 1)`). */
export function squareDragBox(
  ox: number,
  oy: number,
  wx: number,
  wy: number,
): Box {
  const s = Math.max(Math.abs(wx - ox), Math.abs(wy - oy));
  const ex = ox + Math.sign(wx - ox || 1) * s;
  const ey = oy + Math.sign(wy - oy || 1) * s;
  return dragBox(ox, oy, ex, ey);
}

/** The moving endpoint of an arrow / line drag from origin `(ox, oy)` to cursor `(wx, wy)`.
 * With `snap45` the segment angle snaps to the nearest 45° while preserving the cursor's
 * distance from the origin; without it the cursor position passes through unchanged. */
export function arrowDragPoint(
  ox: number,
  oy: number,
  wx: number,
  wy: number,
  snap45: boolean,
): [number, number] {
  if (!snap45) return [wx, wy];
  const len = Math.hypot(wx - ox, wy - oy);
  const step = Math.PI / 4;
  const ang = Math.round(Math.atan2(wy - oy, wx - ox) / step) * step;
  return [ox + Math.cos(ang) * len, oy + Math.sin(ang) * len];
}
