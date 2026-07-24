import {
  hasUnpricedUsage,
  resolveTurnCost,
  resolveTurnDisplayMoney,
} from "@/lib/cost";
import { describe, expect, it } from "vitest";

describe("resolveTurnCost", () => {
  it("prefers the authoritative turn total when known", () => {
    expect(resolveTurnCost(28, [10, 5])).toBe(28);
  });

  it("returns a known total of 0 verbatim (known, not unknown)", () => {
    expect(resolveTurnCost(0, [10])).toBe(0);
  });

  it("falls back to the run sum when there is no turn total (stopped/crashed)", () => {
    expect(resolveTurnCost(null, [10, 5])).toBe(15);
  });

  it("returns null when there is nothing real to show (无花销不显，§7.5)", () => {
    expect(resolveTurnCost(null, [0, 0])).toBeNull();
    expect(resolveTurnCost(null, [])).toBeNull();
  });
});

describe("resolveTurnDisplayMoney", () => {
  it("prefers turn billed total, then estimated_total", () => {
    expect(
      resolveTurnDisplayMoney({ total: 28, estimated_total: 99 }, []),
    ).toEqual({ nano: 28, estimated: false });
    expect(
      resolveTurnDisplayMoney({ total: 0, estimated_total: 99 }, []),
    ).toEqual({ nano: 99, estimated: true });
  });

  it("falls back to run estimated sum when turn cost is absent", () => {
    expect(
      resolveTurnDisplayMoney(null, [
        { total: 0, estimated_total: 10 },
        { total: 0, estimated_total: 5 },
      ]),
    ).toEqual({ nano: 15, estimated: true });
  });

  it("treats user_defined run totals as BYOK estimates", () => {
    expect(
      resolveTurnDisplayMoney(null, [
        { total: 10, pricing_source: "user_defined" },
        { total: 5, pricing_source: "user_defined" },
      ]),
    ).toEqual({ nano: 15, estimated: true });
  });

  it("returns null when nothing real to show", () => {
    expect(resolveTurnDisplayMoney(null, [])).toBeNull();
    expect(
      resolveTurnDisplayMoney(null, [{ total: 0 }, { total: 0 }]),
    ).toBeNull();
  });
});

describe("hasUnpricedUsage", () => {
  const spent = { input: 1000, output: 200 };
  const idle = { input: 0, output: 0 };

  it("flags a run that burned tokens under pricing_source=unpriced", () => {
    expect(
      hasUnpricedUsage([
        { cost: { total: 0, pricing_source: "unpriced" }, usage: spent },
      ]),
    ).toBe(true);
  });

  it("ignores priced/estimated runs and zero-usage unpriced runs", () => {
    expect(
      hasUnpricedUsage([
        { cost: { total: 10, pricing_source: "curated" }, usage: spent },
        { cost: { total: 0, estimated_total: 5 }, usage: spent },
        { cost: { total: 0, pricing_source: "unpriced" }, usage: idle },
        { cost: { total: 0, pricing_source: "unpriced" }, usage: null },
        null,
      ]),
    ).toBe(false);
  });
});
