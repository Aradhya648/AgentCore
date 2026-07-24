import { describe, expect, it } from "vitest";
import { detectReviewConcern, isReviewLikeWorker } from "../reviewConcern";

const reviewer = { role: "学术审校员", runId: "review" };
const researcher = { role: "研究员", runId: "research" };

describe("isReviewLikeWorker", () => {
  it("matches playbook review id and QC role names", () => {
    expect(isReviewLikeWorker("学术审校员", "write")).toBe(true);
    expect(isReviewLikeWorker("工程师", "review")).toBe(true);
    expect(isReviewLikeWorker("研究员", "research")).toBe(false);
  });
});

describe("detectReviewConcern", () => {
  it("flags low numeric scores for review workers", () => {
    expect(detectReviewConcern("语言体验 7/10，有几处可优化", reviewer)).toBe(
      "warning",
    );
    expect(detectReviewConcern("综合评分 4/10，问题较多", reviewer)).toBe(
      "critical",
    );
  });

  it("flags direction-critical wording for review workers", () => {
    expect(detectReviewConcern("整体方向偏书面，建议重写", reviewer)).toBe(
      "critical",
    );
  });

  it("ignores short or neutral text", () => {
    expect(detectReviewConcern("ok", reviewer)).toBeNull();
    expect(
      detectReviewConcern("语法通顺，微调两处即可。", reviewer),
    ).toBeNull();
  });

  it("does not flag non-review workers (graph badge false positives)", () => {
    expect(
      detectReviewConcern("从整体方向把握市场趋势，结论如下。", researcher),
    ).toBeNull();
    expect(
      detectReviewConcern("综合评分 4/10，问题较多", researcher),
    ).toBeNull();
  });

  it("ignores date-like N/10 without grading context", () => {
    expect(
      detectReviewConcern("预计 7/10 完成第一版交付。", reviewer),
    ).toBeNull();
    expect(detectReviewConcern("工期约 3/10 天。", reviewer)).toBeNull();
  });
});
