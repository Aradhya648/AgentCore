import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  type CanvasTurnView,
  loadCanvasTurnView,
  persistCanvasTurnView,
  resolveCanvasTurnView,
} from "../canvasTurnView";

describe("resolveCanvasTurnView", () => {
  it("prefers saved when still available, else natural default", () => {
    const available = new Set(["room", "compare", "graph"] as const);
    expect(resolveCanvasTurnView("compare", "room", available)).toBe("compare");
    expect(
      resolveCanvasTurnView("timeline" as CanvasTurnView, "room", available),
    ).toBe("room");
  });
});

describe("canvas turn view persistence (vitest env = node → stub uiStorage backend)", () => {
  const KEY = "agentcore:canvas-turn-views";
  let store: Record<string, string>;

  beforeEach(() => {
    store = {};
    (globalThis as { localStorage?: Storage }).localStorage = {
      getItem: (k: string) => (k in store ? store[k] : null),
      setItem: (k: string, v: string) => {
        store[k] = v;
      },
      removeItem: (k: string) => {
        delete store[k];
      },
      clear: () => {
        store = {};
      },
      key: (i: number) => Object.keys(store)[i] ?? null,
      get length() {
        return Object.keys(store).length;
      },
    } as Storage;
  });

  afterEach(() => {
    (globalThis as { localStorage?: Storage }).localStorage = undefined;
  });

  it("round-trips a saved `compare` view and drops unknown values", () => {
    persistCanvasTurnView("conv", "t1", "compare");
    expect(loadCanvasTurnView("conv", "t1")).toBe("compare");
    // Foreign / stale keys never resolve to a view.
    store[KEY] = JSON.stringify({
      "conv:t2": "arena",
      "conv:t3": "graph",
      "conv:t4": "revisions",
      "conv:t5": "timeline",
    });
    expect(loadCanvasTurnView("conv", "t2")).toBeNull();
    expect(loadCanvasTurnView("conv", "t3")).toBe("graph");
    expect(loadCanvasTurnView("conv", "t4")).toBeNull();
    expect(loadCanvasTurnView("conv", "t5")).toBeNull();
  });
});
