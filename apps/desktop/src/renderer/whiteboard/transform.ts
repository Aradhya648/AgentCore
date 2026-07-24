/**
 * Pure geometry transforms for the whiteboard engine (AI协作白板.md §六 自研引擎架构).
 *
 * Stateless math lifted out of {@link WhiteboardEngine}: handle-drag resize (single element),
 * multi-select proportional scale, freedraw bbox normalization, arrow bbox bookkeeping, and
 * rotation drag. Same nature as the sibling pure modules (snap / layout / selectionOps) —
 * the engine owns the scene + history and only calls these; nothing here touches engine state.
 */

import { cloneElements } from "./clone";
import { smoothFreedraw } from "./freedrawSmooth";
import { type Box, elementBox, isLinear } from "./geometry";
import type { SceneElement } from "./types";

/** Compute a new rotation (radians) from a drag starting at `startAngle` with base `startRotation`. */
export function rotationFromDrag(
  cx: number,
  cy: number,
  px: number,
  py: number,
  startAngle: number,
  startRotation: number,
): number {
  const angle = Math.atan2(py - cy, px - cx);
  return startRotation + (angle - startAngle);
}

/** Recompute an arrow's bbox (x/y/width/height) from its world points, so selection +
 * marquee work. Rendering uses the points/bindings directly; the box is bookkeeping. */
export function syncArrowBox(el: SceneElement): void {
  const pts = el.points;
  if (!pts || pts.length === 0) return;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const [px, py] of pts) {
    minX = Math.min(minX, px);
    minY = Math.min(minY, py);
    maxX = Math.max(maxX, px);
    maxY = Math.max(maxY, py);
  }
  el.x = minX;
  el.y = minY;
  el.width = maxX - minX;
  el.height = maxY - minY;
}

/** Recenter a freedraw element's bbox so x/y is the points' min corner (points become
 * relative to it), then smooth the stroke. Mutates `el` in place. */
export function normalizeFreedraw(el: SceneElement): void {
  const pts = el.points ?? [];
  if (pts.length === 0) return;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const [px, py] of pts) {
    minX = Math.min(minX, px);
    minY = Math.min(minY, py);
    maxX = Math.max(maxX, px);
    maxY = Math.max(maxY, py);
  }
  el.x += minX;
  el.y += minY;
  el.width = maxX - minX;
  el.height = maxY - minY;
  el.points = pts.map(([px, py]) => [px - minX, py - minY] as [number, number]);
  smoothFreedraw(el);
}

/** Compute the new box when dragging a resize handle of a single element. With `lockAspect`
 * (Shift), the original aspect ratio is preserved: corner handles anchor the opposite corner;
 * edge handles scale the cross axis symmetrically about the box center. */
export function resizeBox(
  box: Box,
  handle: string,
  wx: number,
  wy: number,
  lockAspect: boolean,
): Box {
  const b = box;
  const h = handle;
  let left = b.x;
  let top = b.y;
  let right = b.x + b.width;
  let bottom = b.y + b.height;

  if (lockAspect && b.width > 0 && b.height > 0) {
    const aspect = b.width / b.height;
    const horiz = h.includes("w") || h.includes("e");
    const vert = h.includes("n") || h.includes("s");
    // The edge NOT being dragged stays fixed (the anchor).
    const ax = h.includes("w") ? b.x + b.width : b.x;
    const ay = h.includes("n") ? b.y + b.height : b.y;
    if (horiz && vert) {
      let dw = wx - ax;
      let dh = wy - ay;
      // Follow whichever axis the cursor pushed further (relative to the start size).
      if (Math.abs(dw) / b.width >= Math.abs(dh) / b.height) {
        dh =
          ((dh !== 0 ? Math.sign(dh) : h.includes("n") ? -1 : 1) *
            Math.abs(dw)) /
          aspect;
      } else {
        dw =
          (dw !== 0 ? Math.sign(dw) : h.includes("w") ? -1 : 1) *
          Math.abs(dh) *
          aspect;
      }
      left = Math.min(ax, ax + dw);
      right = Math.max(ax, ax + dw);
      top = Math.min(ay, ay + dh);
      bottom = Math.max(ay, ay + dh);
    } else if (horiz) {
      const dw = wx - ax;
      const newH = Math.abs(dw) / aspect;
      const cy = b.y + b.height / 2;
      left = Math.min(ax, ax + dw);
      right = Math.max(ax, ax + dw);
      top = cy - newH / 2;
      bottom = cy + newH / 2;
    } else {
      const dh = wy - ay;
      const newW = Math.abs(dh) * aspect;
      const cx = b.x + b.width / 2;
      top = Math.min(ay, ay + dh);
      bottom = Math.max(ay, ay + dh);
      left = cx - newW / 2;
      right = cx + newW / 2;
    }
  } else {
    if (h.includes("w")) left = wx;
    if (h.includes("e")) right = wx;
    if (h.includes("n")) top = wy;
    if (h.includes("s")) bottom = wy;
  }

  const minSize = 8;
  return {
    x: Math.min(left, right),
    y: Math.min(top, bottom),
    width: Math.max(minSize, Math.abs(right - left)),
    height: Math.max(minSize, Math.abs(bottom - top)),
  };
}

/** Scale every selected element proportionally when dragging a multi-selection handle.
 * Returns a new array: untouched elements keep their refs; scaled ones are deep-cloned. */
export function scaleElements(
  base: SceneElement[],
  selectedIds: Set<string>,
  box: Box,
  handle: string,
  wx: number,
  wy: number,
  lockAspect: boolean,
): SceneElement[] {
  const b = box;
  const h = handle;
  let left = b.x;
  let top = b.y;
  let right = b.x + b.width;
  let bottom = b.y + b.height;

  if (h.includes("w")) left = wx;
  if (h.includes("e")) right = wx;
  if (h.includes("n")) top = wy;
  if (h.includes("s")) bottom = wy;

  let newW = Math.max(8, Math.abs(right - left));
  let newH = Math.max(8, Math.abs(bottom - top));

  if (lockAspect && b.width > 0 && b.height > 0) {
    const aspect = b.width / b.height;
    if (newW / newH > aspect) newW = newH * aspect;
    else newH = newW / aspect;
    if (h.includes("w")) left = right - newW;
    else right = left + newW;
    if (h.includes("n")) top = bottom - newH;
    else bottom = top + newH;
  }

  const anchorX = h.includes("w") ? b.x + b.width : b.x;
  const anchorY = h.includes("n") ? b.y + b.height : b.y;
  const scaleX = newW / b.width;
  const scaleY = newH / b.height;

  return base.map((el) => {
    if (!selectedIds.has(el.id) || el.locked) return el;
    const copy = cloneElements([el])[0];
    const eb = elementBox(el);
    copy.x = anchorX + (eb.x - anchorX) * scaleX;
    copy.y = anchorY + (eb.y - anchorY) * scaleY;
    copy.width = eb.width * scaleX;
    copy.height = eb.height * scaleY;
    if (isLinear(copy.type) && copy.points) {
      copy.points = copy.points.map(
        ([px, py]) =>
          [
            anchorX + (px - anchorX) * scaleX,
            anchorY + (py - anchorY) * scaleY,
          ] as [number, number],
      );
    }
    return copy;
  });
}
