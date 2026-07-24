import { describe, expect, it } from "vitest";
import { computeMoveSnap } from "../snap";
import type { SceneElement } from "../types";

function rect(id: string, x: number, y: number): SceneElement {
  return {
    id,
    type: "rectangle",
    x,
    y,
    width: 100,
    height: 60,
    schemaVersion: 1,
  };
}

describe("computeMoveSnap", () => {
  it("snaps a moving selection edge to a nearby element", () => {
    const elements = [rect("a", 0, 0), rect("b", 200, 0)];
    const result = computeMoveSnap(elements, new Set(["a"]), 5, 0);
    // a's right edge at 100 + 5 = 105; b's left at 200 — no snap on x from this delta
    expect(result.dx).toBe(5);
    expect(result.dy).toBe(0);
  });

  it("snaps when within threshold", () => {
    const elements = [rect("a", 0, 0), rect("b", 110, 0)];
    const result = computeMoveSnap(elements, new Set(["a"]), 5, 0);
    // a right would be 105, b left is 110 → snap +5
    expect(result.dx).toBe(10);
    expect(result.guides.length).toBeGreaterThan(0);
  });
});
