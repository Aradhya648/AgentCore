/** Deep-clone scene elements — the single source for the per-mutation copies that history
 * snapshots, the AI op-applier, and the clipboard all need (was triplicated). The mutable
 * nested fields (`points`, `groupIds`, `start`, `end`) are copied so a clone never aliases
 * the original's arrays/objects. */

import type { SceneElement } from "./types";

export function cloneElement(e: SceneElement): SceneElement {
  return {
    ...e,
    points: e.points
      ? e.points.map((p) => [p[0], p[1]] as [number, number])
      : undefined,
    groupIds: e.groupIds ? [...e.groupIds] : undefined,
    start: e.start ? { ...e.start } : undefined,
    end: e.end ? { ...e.end } : undefined,
  };
}

export function cloneElements(els: readonly SceneElement[]): SceneElement[] {
  return els.map(cloneElement);
}
