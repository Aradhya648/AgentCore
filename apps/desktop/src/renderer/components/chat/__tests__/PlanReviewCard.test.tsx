// @vitest-environment jsdom
/**
 * 方案 C「一个焦点 + 一个入口」：plan_review 挂起态在时间线降级为单行拍板标记
 * （完整上下文归 ResumePrompt 拍板中心）；resolved 不再占时间线一行，结论收进图节点徽标。
 */

import type { PlanReviewDisplay } from "@/stores/conversation";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PlanReviewCard } from "../PlanReviewCard";

function makeReview(
  overrides: Partial<PlanReviewDisplay> = {},
): PlanReviewDisplay {
  return {
    id: "pr-1",
    steps: [{ run_id: "r1", role: "调研", summary: "方案就绪" }],
    pending: [{ run_id: "r2", role: "执行" }],
    status: "pending",
    decision: null,
    note: "",
    ...overrides,
  };
}

afterEach(cleanup);

describe("PlanReviewCard", () => {
  it("pending 降级为单行拍板标记：无标题卡、无步骤明细、无按钮", () => {
    render(<PlanReviewCard review={makeReview()} />);

    const marker = screen.getByTestId("pending-decision-marker");
    expect(marker.textContent).toContain(
      "等你确认 · 计划复核 · 确认后才会继续",
    );
    expect(marker.textContent).toContain("入口在下方拍板卡");
    expect(screen.queryByText("等待确认")).toBeNull();
    expect(screen.queryByText("调研")).toBeNull();
    expect(screen.queryByText("方案就绪")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("resolved 不渲染时间线行（结论收进图节点徽标）", () => {
    const { container } = render(
      <PlanReviewCard
        review={makeReview({
          status: "resolved",
          decision: "adjust",
          note: "先补充成本数据",
        })}
      />,
    );

    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("pending-decision-marker")).toBeNull();
    expect(screen.queryByText(/已调整/)).toBeNull();
    expect(screen.queryByText("方案就绪")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("resolved stop 同样不占时间线行", () => {
    const { container } = render(
      <PlanReviewCard
        review={makeReview({ status: "resolved", decision: "stop" })}
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText(/已停止/)).toBeNull();
  });
});
