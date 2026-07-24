// @vitest-environment jsdom
/**
 * 方案 C「一个焦点 + 一个入口」：plan_review 挂起态在时间线降级为单行拍板标记
 * （完整上下文归 ResumePrompt 拍板中心）；resolved 留痕默认折叠一行结论，展开见步骤。
 */

import type { PlanReviewDisplay } from "@/stores/conversation";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlanReviewCard } from "../PlanReviewCard";

vi.mock("@/stores/disclosure", () => ({
  usePersistentDisclosure: (_key: string | null, initial: boolean) => {
    const { useState } = require("react");
    return useState(initial);
  },
}));

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

  it("resolved 默认收起为一行结论，不含步骤摘要与备注", () => {
    render(
      <PlanReviewCard
        review={makeReview({
          status: "resolved",
          decision: "adjust",
          note: "先补充成本数据",
        })}
      />,
    );

    expect(
      screen.getByRole("button", {
        name: /已调整 · 指示已注入下游并继续 · 调研/,
      }),
    ).toBeTruthy();
    expect(screen.queryByText("方案就绪")).toBeNull();
    expect(screen.queryByText("先补充成本数据")).toBeNull();
    expect(screen.queryByTestId("pending-decision-marker")).toBeNull();
  });

  it("resolved 展开后可见步骤摘要与备注", () => {
    render(
      <PlanReviewCard
        review={makeReview({
          status: "resolved",
          decision: "adjust",
          note: "先补充成本数据",
        })}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: /已调整 · 指示已注入下游并继续 · 调研/,
      }),
    );
    expect(screen.getByText("调研")).toBeTruthy();
    expect(screen.getByText("方案就绪")).toBeTruthy();
    expect(screen.getByText("先补充成本数据")).toBeTruthy();
  });

  it("resolved stop 显示未放行下游", () => {
    render(
      <PlanReviewCard
        review={makeReview({ status: "resolved", decision: "stop" })}
      />,
    );
    expect(
      screen.getByRole("button", { name: /已停止 · 未运行下游 · 调研/ }),
    ).toBeTruthy();
  });
});
