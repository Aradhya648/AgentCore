/** Edge/center snap while dragging — pure, testable (world coords). */

import { type Box, elementBox, unionBox } from "./geometry";
import type { SceneElement } from "./types";

const SNAP_THRESHOLD = 8;

export interface SnapResult {
  dx: number;
  dy: number;
  guides: Array<[number, number, number, number]>;
}

function axisLines(b: Box): { x: number[]; y: number[] } {
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  return {
    x: [b.x, cx, b.x + b.width],
    y: [b.y, cy, b.y + b.height],
  };
}

/** Snap a moving selection's bbox edges/centers to nearby unselected elements. */
export function computeMoveSnap(
  elements: readonly SceneElement[],
  selected: ReadonlySet<string>,
  dx: number,
  dy: number,
): SnapResult {
  if (selected.size === 0 || (dx === 0 && dy === 0)) {
    return { dx, dy, guides: [] };
  }

  const selBox = unionBox(elements.filter((e) => selected.has(e.id)));
  if (!selBox) return { dx, dy, guides: [] };

  const moving: Box = {
    x: selBox.x + dx,
    y: selBox.y + dy,
    width: selBox.width,
    height: selBox.height,
  };
  const moveLines = axisLines(moving);

  let snapDx = 0;
  let snapDy = 0;
  let bestDistX = SNAP_THRESHOLD + 1;
  let bestDistY = SNAP_THRESHOLD + 1;
  let guideX: number | null = null;
  let guideY: number | null = null;

  for (const el of elements) {
    if (selected.has(el.id) || el.locked) continue;
    const target = axisLines(elementBox(el));

    for (const mv of moveLines.x) {
      for (const tv of target.x) {
        const dist = Math.abs(mv - tv);
        if (dist <= SNAP_THRESHOLD && dist < bestDistX) {
          bestDistX = dist;
          snapDx = tv - mv;
          guideX = tv;
        }
      }
    }
    for (const mh of moveLines.y) {
      for (const th of target.y) {
        const dist = Math.abs(mh - th);
        if (dist <= SNAP_THRESHOLD && dist < bestDistY) {
          bestDistY = dist;
          snapDy = th - mh;
          guideY = th;
        }
      }
    }
  }

  const guides: Array<[number, number, number, number]> = [];
  const span = 4000;
  if (guideX !== null) {
    guides.push([
      guideX,
      moving.y - span,
      guideX,
      moving.y + moving.height + span,
    ]);
  }
  if (guideY !== null) {
    guides.push([
      moving.x - span,
      guideY,
      moving.x + moving.width + span,
      guideY,
    ]);
  }

  return { dx: dx + snapDx, dy: dy + snapDy, guides };
}
