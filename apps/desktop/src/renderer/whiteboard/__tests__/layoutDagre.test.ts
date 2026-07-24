import { describe, expect, it } from "vitest";
import { layoutDagre } from "../layoutDagre";
import { SCENE_SCHEMA_VERSION, type SceneElement } from "../types";

const box = (
  id: string,
  x: number,
  y: number,
  w = 80,
  h = 40,
): SceneElement => ({
  id,
  type: "rectangle",
  x,
  y,
  width: w,
  height: h,
  schemaVersion: SCENE_SCHEMA_VERSION,
});

describe("layoutDagre", () => {
  it("spreads chained nodes left-to-right without changing count", () => {
    const elements: SceneElement[] = [
      box("a", 0, 0),
      box("b", 0, 120),
      {
        id: "e1",
        type: "arrow",
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        start: { id: "a" },
        end: { id: "b" },
        points: [
          [40, 20],
          [40, 140],
        ] as [number, number][],
        schemaVersion: SCENE_SCHEMA_VERSION,
      },
    ];
    const next = layoutDagre(elements, new Set(["a", "b", "e1"]));
    const a = next.find((e) => e.id === "a");
    const b = next.find((e) => e.id === "b");
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    if (!a || !b) throw new Error("layout nodes missing");
    expect(b.x).toBeGreaterThan(a.x);
    expect(next.length).toBe(elements.length);
  });
});
