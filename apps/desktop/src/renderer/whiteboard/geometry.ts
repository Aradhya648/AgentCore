/** Pure geometry helpers: world↔screen transform, bounding boxes, hit testing. */

import type { SceneElement, Viewport } from "./types";

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Linear elements (a polyline of points + optional endpoint bindings): `arrow` and `line`.
 * They share hit-testing, endpoint resolution, point translation and "no box handles" — the
 * only difference is `line` draws without an arrowhead. */
export function isLinear(type: SceneElement["type"]): boolean {
  return type === "arrow" || type === "line";
}

export function worldToScreen(
  v: Viewport,
  wx: number,
  wy: number,
): [number, number] {
  return [wx * v.zoom + v.panX, wy * v.zoom + v.panY];
}

export function screenToWorld(
  v: Viewport,
  sx: number,
  sy: number,
): [number, number] {
  return [(sx - v.panX) / v.zoom, (sy - v.panY) / v.zoom];
}

/** Normalized (always-positive width/height) bounding box of an element. */
export function elementBox(el: SceneElement): Box {
  const x = el.width < 0 ? el.x + el.width : el.x;
  const y = el.height < 0 ? el.y + el.height : el.y;
  return { x, y, width: Math.abs(el.width), height: Math.abs(el.height) };
}

export function unionBox(els: readonly SceneElement[]): Box | null {
  if (els.length === 0) return null;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const el of els) {
    const b = elementBox(el);
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.width);
    maxY = Math.max(maxY, b.y + b.height);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

export function pointInBox(px: number, py: number, b: Box, pad = 0): boolean {
  return (
    px >= b.x - pad &&
    px <= b.x + b.width + pad &&
    py >= b.y - pad &&
    py <= b.y + b.height + pad
  );
}

export function boxesIntersect(a: Box, b: Box): boolean {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

export function distToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

/** Center point of an element's box (world). */
export function elementCenter(el: SceneElement): [number, number] {
  const b = elementBox(el);
  return [b.x + b.width / 2, b.y + b.height / 2];
}

/** Resolve an arrow's two endpoints (world). Bound endpoints use the bound element's
 * center, clipped to its box edge toward the other end so the arrow touches the border
 * rather than the middle. Unbound endpoints fall back to the arrow's own points. */
export function arrowEndpoints(
  el: SceneElement,
  byId: ReadonlyMap<string, SceneElement>,
): [[number, number], [number, number]] {
  const pts = el.points ?? [];
  const fallbackStart: [number, number] = pts[0] ?? [el.x, el.y];
  const fallbackEnd: [number, number] = pts[pts.length - 1] ?? [
    el.x + el.width,
    el.y + el.height,
  ];
  const startEl = el.start?.id ? byId.get(el.start.id) : undefined;
  const endEl = el.end?.id ? byId.get(el.end.id) : undefined;
  const startC: [number, number] = startEl
    ? elementCenter(startEl)
    : fallbackStart;
  const endC: [number, number] = endEl ? elementCenter(endEl) : fallbackEnd;
  const start = startEl ? clipToBox(startEl, endC) : startC;
  const end = endEl ? clipToBox(endEl, startC) : endC;
  return [start, end];
}

/** Point on an element box's border along the ray from its center toward `toward`. */
function clipToBox(
  el: SceneElement,
  toward: [number, number],
): [number, number] {
  const b = elementBox(el);
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  const dx = toward[0] - cx;
  const dy = toward[1] - cy;
  if (dx === 0 && dy === 0) return [cx, cy];
  const halfW = b.width / 2;
  const halfH = b.height / 2;
  const scale = 1 / Math.max(Math.abs(dx) / halfW, Math.abs(dy) / halfH);
  return [cx + dx * scale, cy + dy * scale];
}

/** Whether a world point hits an element, with a world-space tolerance for thin shapes. */
export function hitTestElement(
  el: SceneElement,
  wx: number,
  wy: number,
  tol: number,
  byId: ReadonlyMap<string, SceneElement>,
): boolean {
  if (isLinear(el.type)) {
    const [a, b] = arrowEndpoints(el, byId);
    return distToSegment(wx, wy, a[0], a[1], b[0], b[1]) <= tol;
  }
  if (el.type === "freedraw") {
    const pts = el.points ?? [];
    for (let i = 1; i < pts.length; i++) {
      const x1 = el.x + pts[i - 1][0];
      const y1 = el.y + pts[i - 1][1];
      const x2 = el.x + pts[i][0];
      const y2 = el.y + pts[i][1];
      if (distToSegment(wx, wy, x1, y1, x2, y2) <= tol) return true;
    }
    return pts.length === 1
      ? Math.hypot(wx - (el.x + pts[0][0]), wy - (el.y + pts[0][1])) <= tol
      : false;
  }
  const b = elementBox(el);
  if (el.rotation) {
    // Inverse-rotate the test point into the element's local (unrotated) frame.
    const cx = b.x + b.width / 2;
    const cy = b.y + b.height / 2;
    const cos = Math.cos(-el.rotation);
    const sin = Math.sin(-el.rotation);
    const dx = wx - cx;
    const dy = wy - cy;
    return pointInBox(
      cx + dx * cos - dy * sin,
      cy + dx * sin + dy * cos,
      b,
      tol,
    );
  }
  return pointInBox(wx, wy, b, tol);
}
