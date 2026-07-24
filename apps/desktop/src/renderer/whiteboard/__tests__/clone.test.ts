import { describe, expect, it } from "vitest";
import { cloneElement, cloneElements } from "../clone";
import type { SceneElement } from "../types";

const base = (p: Partial<SceneElement> & { id: string }): SceneElement => ({
  type: "rectangle",
  x: 0,
  y: 0,
  width: 10,
  height: 10,
  schemaVersion: 1,
  ...p,
});

describe("cloneElement", () => {
  it("copies scalar fields", () => {
    const src = base({ id: "a", x: 5, y: 6, text: "hi", fill: "red" });
    expect(cloneElement(src)).toEqual(src);
  });

  it("deep-copies points so the clone never aliases the source array", () => {
    const src = base({
      id: "a",
      type: "freedraw",
      points: [
        [0, 0],
        [1, 1],
      ],
    });
    const copy = cloneElement(src);
    expect(copy.points).toEqual(src.points);
    expect(copy.points).not.toBe(src.points);
    copy.points?.push([2, 2]);
    expect(src.points).toHaveLength(2);
  });

  it("deep-copies groupIds, start, and end bindings", () => {
    const src = base({
      id: "arr",
      type: "arrow",
      groupIds: ["g1"],
      start: { id: "x" },
      end: { id: "y" },
    });
    const copy = cloneElement(src);
    expect(copy.groupIds).not.toBe(src.groupIds);
    expect(copy.start).not.toBe(src.start);
    expect(copy.end).not.toBe(src.end);
    if (copy.start) copy.start.id = "z";
    expect(src.start?.id).toBe("x");
  });

  it("leaves undefined optional fields undefined (no empty arrays/objects)", () => {
    const copy = cloneElement(base({ id: "a" }));
    expect(copy.points).toBeUndefined();
    expect(copy.groupIds).toBeUndefined();
    expect(copy.start).toBeUndefined();
  });
});

describe("cloneElements", () => {
  it("clones every element into a new array", () => {
    const src = [base({ id: "a" }), base({ id: "b" })];
    const copy = cloneElements(src);
    expect(copy).toEqual(src);
    expect(copy).not.toBe(src);
    expect(copy[0]).not.toBe(src[0]);
  });
});
