import { describe, expect, it } from "vitest";
import {
  LAYOUT_PADDING,
  NODE_HEIGHT,
  NODE_WIDTH,
  buildNodeSizeMap,
  computeVisualBbox,
  measuredHeightsMatchSizes,
  nodeVisualHeight,
  placedNodeY,
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

describe("graphMetrics · visual footprint (fit-width lag window)", () => {
  it("nodeVisualHeight rises when measured exceeds layout slot", () => {
    expect(nodeVisualHeight(NODE_HEIGHT, 200)).toBe(200);
    expect(nodeVisualHeight(NODE_HEIGHT, undefined)).toBe(NODE_HEIGHT);
    expect(nodeVisualHeight(NODE_HEIGHT, 80)).toBe(NODE_HEIGHT);
  });

  it("placedNodeY soft-centers like projectFlowGraph.placed", () => {
    expect(placedNodeY(24, 110, 200)).toBe(24 + (110 - 200) / 2);
    expect(placedNodeY(24, 110, undefined)).toBe(24);
  });

  it("computeVisualBbox raises height when measured > slot (no secondary ELK)", () => {
    const positions = { a: { x: LAYOUT_PADDING, y: LAYOUT_PADDING } };
    const sizes = { a: { width: NODE_WIDTH, height: NODE_HEIGHT } };
    const layoutBbox = {
      width: LAYOUT_PADDING + NODE_WIDTH + LAYOUT_PADDING,
      height: LAYOUT_PADDING + NODE_HEIGHT + LAYOUT_PADDING,
    };
    const cold = computeVisualBbox(positions, sizes, {}, layoutBbox);
    expect(cold.height).toBe(layoutBbox.height);
    expect(cold.width).toBe(layoutBbox.width);
    expect(cold.originY).toBe(0);

    const grown = computeVisualBbox(positions, sizes, { a: 200 }, layoutBbox);
    expect(grown.height).toBeGreaterThan(layoutBbox.height);
    // Soft-center spills above y=0 → originY negative; height covers full card.
    expect(grown.originY).toBeLessThan(0);
    const top = placedNodeY(LAYOUT_PADDING, NODE_HEIGHT, 200);
    const bottom = top + 200;
    expect(grown.height).toBe(bottom + LAYOUT_PADDING + Math.max(0, -top));
  });

  it("computeVisualBbox never shrinks below layout bbox", () => {
    const positions = { a: { x: 40, y: 40 } };
    const sizes = { a: { width: NODE_WIDTH, height: NODE_HEIGHT } };
    const layoutBbox = { width: 900, height: 700 };
    const out = computeVisualBbox(positions, sizes, { a: 50 }, layoutBbox);
    expect(out.width).toBe(900);
    expect(out.height).toBe(700);
  });
});
