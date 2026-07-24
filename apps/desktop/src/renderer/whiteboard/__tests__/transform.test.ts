import { describe, expect, it } from "vitest";
import { rotationFromDrag } from "../transform";

describe("rotationFromDrag", () => {
  it("adds pointer angle delta to the start rotation", () => {
    const start = rotationFromDrag(0, 0, 1, 0, 0, 0);
    expect(start).toBeCloseTo(0);
    const quarter = rotationFromDrag(0, 0, 0, 1, 0, 0);
    expect(quarter).toBeCloseTo(Math.PI / 2);
    const continued = rotationFromDrag(0, 0, 0, 1, 0, 1);
    expect(continued).toBeCloseTo(1 + Math.PI / 2);
  });
});
