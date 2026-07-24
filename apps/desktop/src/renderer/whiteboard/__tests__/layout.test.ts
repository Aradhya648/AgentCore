import { describe, expect, it } from "vitest";
import { layoutGrid } from "../layout";
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

describe("layoutGrid", () => {
  it("arranges selected elements in a grid from the anchor top-left", () => {
    const elements = [
      rect("a", 10, 10),
      rect("b", 200, 50),
      rect("c", 400, 80),
    ];
    const next = layoutGrid(elements, new Set(["a", "b", "c"]), {
      cols: 2,
      gap: 20,
    });
    const a = next.find((e) => e.id === "a");
    const b = next.find((e) => e.id === "b");
    const c = next.find((e) => e.id === "c");
    expect(a?.x).toBe(10);
    expect(a?.y).toBe(10);
    expect(b?.x).toBe(10 + 100 + 20);
    expect(b?.y).toBe(10);
    expect(c?.x).toBe(10);
    expect(c?.y).toBe(10 + 60 + 20);
  });

  it("leaves unselected elements untouched", () => {
    const elements = [rect("a", 0, 0), rect("b", 300, 0)];
    const next = layoutGrid(elements, new Set(["a"]), { cols: 1 });
    expect(next.find((e) => e.id === "b")?.x).toBe(300);
  });
});
