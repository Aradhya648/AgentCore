import { describe, expect, it } from "vitest";
import { parseRiskLabel } from "../parseRiskLabel";

describe("parseRiskLabel", () => {
  it("parses [高]/[中]/[低] prefixes", () => {
    expect(parseRiskLabel("[高] 密钥轮换")).toEqual({
      severity: "high",
      text: "密钥轮换",
    });
    expect(parseRiskLabel("[中]备份校验")).toEqual({
      severity: "medium",
      text: "备份校验",
    });
    expect(parseRiskLabel("[低] 文档补齐")).toEqual({
      severity: "low",
      text: "文档补齐",
    });
  });

  it("falls back when prefix is missing", () => {
    expect(parseRiskLabel("密钥轮换")).toEqual({
      severity: null,
      text: "密钥轮换",
    });
  });
});
