import { describe, expect, it } from "vitest";
import {
  NODE_HEIGHT,
  NODE_WIDTH,
  buildNodeSizeMap,
  measuredHeightsMatchSizes,
} from "../graphMetrics";

describe("graphMetrics · measured height helpers", () => {
  it("buildNodeSizeMap overlays positive measured heights", () => {
    const map = buildNodeSizeMap(["a", "b"], { a: 180 });
    expect(map.a).toEqual({ width: NODE_WIDTH, height: 180 });
    expect(map.b).toEqual({ width: NODE_WIDTH, height: NODE_HEIGHT });
  });

  it("measuredHeightsMatchSizes gates sub-eps jitter and detects drift", () => {
    const ids = ["a", "b"];
    const sizes = buildNodeSizeMap(ids, { a: 180, b: 200 });
    expect(measuredHeightsMatchSizes(ids, sizes, { a: 180, b: 200 })).toBe(
      true,
    );
    expect(measuredHeightsMatchSizes(ids, sizes, { a: 180.4, b: 200 })).toBe(
      true,
    );
    expect(measuredHeightsMatchSizes(ids, sizes, { a: 190, b: 200 })).toBe(
      false,
    );
  });
});
