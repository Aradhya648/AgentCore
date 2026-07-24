import { cleanSourceTitle, referencedCitationNumbers } from "@/lib/citations";
import { describe, expect, it } from "vitest";

describe("cleanSourceTitle", () => {
  it("strips a space-padded dash site suffix", () => {
    expect(cleanSourceTitle("深圳天气预报 - 中国天气网")).toBe("深圳天气预报");
  });

  it("strips an unspaced CJK underscore suffix", () => {
    expect(cleanSourceTitle("相对论_百度百科")).toBe("相对论");
  });

  it("strips an English ' - ' site suffix", () => {
    expect(cleanSourceTitle("OpenAI Charter - Wikipedia")).toBe(
      "OpenAI Charter",
    );
  });

  it("keeps titles where a dash is part of the content", () => {
    expect(cleanSourceTitle("2024-2025 年度财政预算报告")).toBe(
      "2024-2025 年度财政预算报告",
    );
  });

  it("leaves short titles untouched", () => {
    expect(cleanSourceTitle("百度百科")).toBe("百度百科");
  });

  it("handles undefined and blank input", () => {
    expect(cleanSourceTitle(undefined)).toBe("");
    expect(cleanSourceTitle("   ")).toBe("");
  });
});

describe("referencedCitationNumbers", () => {
  it("collects in-range [n] markers in body order", () => {
    expect([...referencedCitationNumbers("see [1] and [3].", 5)]).toEqual([
      1, 3,
    ]);
  });

  it("ignores zero and out-of-range markers", () => {
    expect([...referencedCitationNumbers("[0] [3] [9]", 3)]).toEqual([3]);
  });

  it("dedups repeated markers", () => {
    expect([...referencedCitationNumbers("[2] x [2] y [2]", 3)]).toEqual([2]);
  });

  it("is empty when max is 0 or content is empty", () => {
    expect(referencedCitationNumbers("[1]", 0).size).toBe(0);
    expect(referencedCitationNumbers("", 5).size).toBe(0);
  });
});
