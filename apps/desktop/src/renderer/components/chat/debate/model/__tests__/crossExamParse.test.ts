import { describe, expect, it } from "vitest";
import { parseCrossExamResponse } from "../crossExamParse";

describe("parseCrossExamResponse", () => {
  it("splits by ### 质询N headings", () => {
    const qs = [
      "收益量化口径是否计入了尾部风险？请是/否直接回答。",
      "若熔断触发、灰度止损，已投入成本由谁承担？",
    ];
    const ans = [
      "### 质询一",
      "否，量化口径未含尾部风险【待核实·推断】。",
      "",
      "### 质询二",
      "成本由灰度预算池兜底、触发熔断即回滚【已核实·灰度预案v2】",
    ].join("\n");
    const got = parseCrossExamResponse(qs, ans);
    expect(got).toHaveLength(2);
    expect(got[0].answer).toContain("尾部");
    expect(got[1].answer).toContain("灰度");
  });

  it("discards preamble before the first heading", () => {
    const qs = ["你这条有出处吗？"];
    const ans = [
      "好的，我已掌握材料，现在作答：",
      "### 质询一",
      "暂无统一出处【待核实·推断】",
    ].join("\n");
    const got = parseCrossExamResponse(qs, ans);
    expect(got).toHaveLength(1);
    expect(got[0].answer).toContain("出处");
    expect(got[0].answer).not.toContain("好的");
  });

  it("hangs whole blob on first question when no headings", () => {
    const qs = ["收益是否计入尾部风险？", "熔断成本由谁承担？"];
    const ans = "作答：否，口径未含尾部【待核实·推断】。";
    const got = parseCrossExamResponse(qs, ans);
    expect(got).toHaveLength(2);
    expect(got[0].answer).toContain("尾部");
    expect(got[1].answer).toBe("");
  });

  it("pads missing sections with empty answers", () => {
    const qs = ["Q1", "Q2"];
    const ans = "### 质询一\n只答了第一条";
    const got = parseCrossExamResponse(qs, ans);
    expect(got[0].answer).toBe("只答了第一条");
    expect(got[1].answer).toBe("");
  });

  it("splits numbered 1. / 2. headings and ignores decimal 3.5", () => {
    const qs = ["Q1", "Q2"];
    const ans = [
      "1. 第一答：口径未含尾部【待核实·推断】。",
      "2. 第二答：成本由灰度预算池兜底；其中 3.5 倍杠杆不改变结论【已核实·预案】。",
    ].join("\n");
    const got = parseCrossExamResponse(qs, ans);
    expect(got).toHaveLength(2);
    expect(got[0].answer).toContain("尾部");
    expect(got[1].answer).toContain("灰度");
    expect(got[1].answer).toContain("3.5");
  });
});
