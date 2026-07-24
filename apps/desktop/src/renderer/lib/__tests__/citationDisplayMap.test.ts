import { buildCitationDisplayMap } from "@/lib/citationDisplayMap";
import { describe, expect, it } from "vitest";

describe("buildCitationDisplayMap", () => {
  it("assigns display numbers by first appearance order", () => {
    const map = buildCitationDisplayMap("see [3] then [1] then [3]", 4);
    expect([...map.stableCited.entries()]).toEqual([
      [3, 1],
      [1, 2],
    ]);
    expect(map.toDisplay.get(3)).toBe(1);
    expect(map.toDisplay.get(1)).toBe(2);
    expect(map.rows.map((r) => [r.poolIndex + 1, r.display, r.cited])).toEqual([
      [3, 1, true],
      [1, 2, true],
      [2, 3, false],
      [4, 4, false],
    ]);
    expect([...map.referencedDisplay].sort()).toEqual([1, 2]);
  });

  it("puts unreferenced sources after cited ones in pool order", () => {
    const map = buildCitationDisplayMap("[2]", 3);
    expect(map.rows.map((r) => r.poolIndex + 1)).toEqual([2, 1, 3]);
    expect(map.rows.every((r, i) => r.display === i + 1)).toBe(true);
  });

  it("ignores out-of-range markers", () => {
    const map = buildCitationDisplayMap("[0] [2] [9]", 2);
    expect([...map.stableCited.entries()]).toEqual([[2, 1]]);
  });

  it("is empty when max is 0 or content is empty", () => {
    expect(buildCitationDisplayMap("[1]", 0).rows).toEqual([]);
    expect(buildCitationDisplayMap("", 3).stableCited.size).toBe(0);
    expect(buildCitationDisplayMap("", 3).rows.map((r) => r.display)).toEqual([
      1, 2, 3,
    ]);
  });

  it("treats #rN as cited when citations[].id matches", () => {
    const citations = [{ id: "#r5" }, { id: "#r3" }, { id: undefined }];
    const map = buildCitationDisplayMap("争议 #r5#r3", 3, null, citations);
    expect(map.toDisplay.get(1)).toBe(1); // #r5 → pool index 0 → canonical 1
    expect(map.toDisplay.get(2)).toBe(2); // #r3
    expect(map.referencedDisplay.has(1)).toBe(true);
    expect(map.referencedDisplay.has(2)).toBe(true);
  });

  it("streaming: appends only — prior display numbers do not jump", () => {
    const frame1 = buildCitationDisplayMap("alpha [3]", 4);
    expect([...frame1.stableCited.entries()]).toEqual([[3, 1]]);

    const frame2 = buildCitationDisplayMap(
      "alpha [3] beta [1]",
      4,
      frame1.stableCited,
    );
    expect([...frame2.stableCited.entries()]).toEqual([
      [3, 1],
      [1, 2],
    ]);
    // Unreferenced trailing slots recompute; cited stay put.
    expect(frame2.toDisplay.get(3)).toBe(1);
    expect(frame2.toDisplay.get(1)).toBe(2);
    expect(frame2.rows.map((r) => [r.poolIndex + 1, r.display])).toEqual([
      [3, 1],
      [1, 2],
      [2, 3],
      [4, 4],
    ]);

    // A later first-cite of what was previously trailing must take the next slot,
    // not keep a stale unreferenced assignment from frame1.
    const early = buildCitationDisplayMap("x [3]", 4);
    // If we wrongly froze unreferenced into previous, [2] would stay at display 3.
    const later = buildCitationDisplayMap("x [3] y [2]", 4, early.stableCited);
    expect(later.toDisplay.get(2)).toBe(2);
    expect(later.toDisplay.get(3)).toBe(1);
  });
});
