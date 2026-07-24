import { describe, expect, it } from "vitest";
import { computeKeepBrightIds, hoverRelatedIds } from "../graphHover";

function sortedIds(set: Set<string> | null): string[] {
  expect(set).not.toBeNull();
  return [...(set ?? [])].sort();
}

describe("hoverRelatedIds", () => {
  const edges = [
    { source: "a", target: "b" },
    { source: "b", target: "c" },
    { source: "x", target: "y" },
  ];

  it("returns null when nothing is hovered", () => {
    expect(hoverRelatedIds(null, edges)).toBeNull();
  });

  it("includes the hovered node and full upstream + downstream path", () => {
    expect(sortedIds(hoverRelatedIds("b", edges))).toEqual(["a", "b", "c"]);
  });

  it("walks past direct neighbors along the chain", () => {
    const chain = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
      { source: "c", target: "d" },
    ];
    expect(sortedIds(hoverRelatedIds("b", chain))).toEqual([
      "a",
      "b",
      "c",
      "d",
    ]);
    expect(sortedIds(hoverRelatedIds("c", chain))).toEqual([
      "a",
      "b",
      "c",
      "d",
    ]);
  });

  it("does not cross into an unrelated component", () => {
    expect(sortedIds(hoverRelatedIds("a", edges))).toEqual(["a", "b", "c"]);
    expect(sortedIds(hoverRelatedIds("x", edges))).toEqual(["x", "y"]);
  });

  it("works with namespaced canvas ids", () => {
    const nested = [
      { source: "t1::a", target: "t1::b" },
      { source: "t1::b", target: "t1::c" },
      { source: "t1::c", target: "t1::d" },
    ];
    expect(sortedIds(hoverRelatedIds("t1::b", nested))).toEqual([
      "t1::a",
      "t1::b",
      "t1::c",
      "t1::d",
    ]);
  });
});

describe("computeKeepBrightIds", () => {
  it("returns null when neither constraint is active", () => {
    expect(computeKeepBrightIds(null, null)).toBeNull();
  });

  it("passes through a single active set", () => {
    const hover = new Set(["a", "b"]);
    expect(computeKeepBrightIds(hover, null)).toBe(hover);
    const inject = new Set(["b", "c"]);
    expect(computeKeepBrightIds(null, inject)).toBe(inject);
  });

  it("intersects hover and inject constraints", () => {
    const hover = new Set(["a", "b", "c"]);
    const inject = new Set(["b", "c", "d"]);
    expect(sortedIds(computeKeepBrightIds(hover, inject))).toEqual(["b", "c"]);
  });
});
