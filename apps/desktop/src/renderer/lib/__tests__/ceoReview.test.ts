import { toCeoReview } from "@/lib/ceoReview";
import { describe, expect, it } from "vitest";

describe("toCeoReview", () => {
  it("parses source llm / deterministic", () => {
    expect(
      toCeoReview({
        conclusion: "可过",
        risks: ["r"],
        suggestions: ["s"],
        source: "llm",
      })?.source,
    ).toBe("llm");
    expect(
      toCeoReview({
        conclusion: "回落",
        risks: [],
        suggestions: [],
        source: "deterministic",
      })?.source,
    ).toBe("deterministic");
  });

  it("omits source when absent or unknown (旧帧)", () => {
    const legacy = toCeoReview({
      conclusion: "旧",
      risks: [],
      suggestions: [],
    });
    expect(legacy).toEqual({ conclusion: "旧", risks: [], suggestions: [] });
    expect("source" in (legacy ?? {})).toBe(false);
    expect(
      toCeoReview({
        conclusion: "x",
        risks: [],
        suggestions: [],
        source: "other",
      })?.source,
    ).toBeUndefined();
  });

  it("returns undefined for empty shell", () => {
    expect(toCeoReview(null)).toBeUndefined();
    expect(
      toCeoReview({ conclusion: "", risks: [], suggestions: [] }),
    ).toBeUndefined();
  });
});
