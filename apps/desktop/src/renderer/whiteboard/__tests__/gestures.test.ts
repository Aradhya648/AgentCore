/**
 * Unit tests for the pure drag-gesture geometry (gestures.ts): the marquee / create rubber-band
 * box (+ its 1:1 square-lock) and the arrow/line endpoint 45° snap. No engine / canvas needed.
 */

import { describe, expect, it } from "vitest";
import { arrowDragPoint, dragBox, squareDragBox } from "../gestures";

describe("dragBox", () => {
  it("spans two corners as a min-corner + absolute-extent box", () => {
    expect(dragBox(10, 20, 40, 60)).toEqual({
      x: 10,
      y: 20,
      width: 30,
      height: 40,
    });
  });

  it("normalizes a drag toward the top-left (cursor above-left of origin)", () => {
    expect(dragBox(40, 60, 10, 20)).toEqual({
      x: 10,
      y: 20,
      width: 30,
      height: 40,
    });
  });

  it("is a zero-size box when the cursor sits on the origin", () => {
    expect(dragBox(5, 5, 5, 5)).toEqual({ x: 5, y: 5, width: 0, height: 0 });
  });
});

describe("squareDragBox", () => {
  it("sizes the square by the larger axis delta (x dominates)", () => {
    // |dx|=100 > |dy|=30 → 100×100 square down-right.
    expect(squareDragBox(0, 0, 100, 30)).toEqual({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
    });
  });

  it("grows into the cursor's quadrant (up-left)", () => {
    // |dy|=80 > |dx|=50 → 80×80 square extending up-left of the origin.
    expect(squareDragBox(0, 0, -50, -80)).toEqual({
      x: -80,
      y: -80,
      width: 80,
      height: 80,
    });
  });

  it("falls back to the positive direction on a zero-delta axis", () => {
    // dx=0 → sign(0 || 1)=+1, so the square extends right as well as down.
    expect(squareDragBox(0, 0, 0, 40)).toEqual({
      x: 0,
      y: 0,
      width: 40,
      height: 40,
    });
  });
});

describe("arrowDragPoint", () => {
  it("passes the cursor through unchanged without snap", () => {
    expect(arrowDragPoint(0, 0, 37, 9, false)).toEqual([37, 9]);
  });

  it("snaps a near-horizontal drag to 0°, preserving length", () => {
    const [x, y] = arrowDragPoint(0, 0, 100, 12, true);
    expect(x).toBeCloseTo(Math.hypot(100, 12));
    expect(y).toBeCloseTo(0);
  });

  it("snaps a ~45° drag onto the diagonal", () => {
    const [x, y] = arrowDragPoint(0, 0, 50, 40, true);
    const len = Math.hypot(50, 40);
    expect(x).toBeCloseTo((len * Math.SQRT2) / 2);
    expect(y).toBeCloseTo((len * Math.SQRT2) / 2);
  });

  it("snaps a near-vertical drag to 90° (upward)", () => {
    const [x, y] = arrowDragPoint(0, 0, 8, -70, true);
    expect(x).toBeCloseTo(0);
    expect(y).toBeCloseTo(-Math.hypot(8, 70));
  });
});
