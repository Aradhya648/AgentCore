// @vitest-environment jsdom
/**
 * 拍板中心 · plan_review：CEO 把关意见（conclusion / risks / suggestions）随
 * `plan_review_required.ceo_review` 渲染进 ResumePrompt；absent（旧帧 / 无摘要）
 * 不渲染摘要区（不留空壳）。
 *
 * A+ 渐进披露：结论卡头常显（长文可展开）；产出/下游一行 meta；风险 Top2 常显，
 * 其余风险与建议进同一「详情」；llm 下发提示收进继续按钮 tooltip。
 */

import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResumePrompt } from "../ResumePrompt";

vi.mock("@/services/interactionSubmit", () => ({
  submitInteraction: vi.fn().mockResolvedValue("ok"),
  submitInteractionFeedback: () => "请稍候再试",
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
}));

const pendingRef: { current: unknown[] } = { current: [] };

vi.mock("@/stores/conversation", () => ({
  useConversationStore: (
    sel: (s: { currentConversationId: string }) => unknown,
  ) => sel({ currentConversationId: "c1" }),
}));

vi.mock("@/stores/pausedTurns", () => ({
  usePausedTurnStore: (sel: (s: { pending: unknown[] }) => unknown) =>
    sel({ pending: pendingRef.current }),
}));

vi.mock("@/stores/interactions", () => ({
  useInteractionStore: (sel: (s: { byId: Map<string, unknown> }) => unknown) =>
    sel({ byId: new Map() }),
}));

vi.mock("@/stores/disclosure", async () => {
  const { useState } = await import("react");
  return {
    usePersistentDisclosure: (_key: string | null, initial: boolean) =>
      useState(initial),
  };
});

function renderPrompt() {
  return render(
    <TooltipProvider>
      <ResumePrompt />
    </TooltipProvider>,
  );
}

function makePlanReview(over: Record<string, unknown> = {}) {
  return {
    messageId: "m1",
    conversationId: "c1",
    checkpointId: "pr1",
    kind: "plan_review",
    userMessage: "分阶段推进",
    userMessageId: "u1",
    steps: [{ run_id: "r1", role: "调研", summary: "方案就绪" }],
    pending: [{ run_id: "r2", role: "执行" }],
    workers: [],
    tools: [],
    primitive: "delegate",
    motion: "",
    form: "",
    sides: [],
    maxRounds: 0,
    thorough: true,
    offerResearchFirst: false,
    researchFirstRecommended: false,
    question: "",
    context: "",
    assumptions: [],
    questions: [],
    styleOptions: [],
    formatOptions: [],
    intent: "decision",
    origin: "server",
    ...over,
  };
}

afterEach(() => {
  cleanup();
  pendingRef.current = [];
});

describe("ResumePrompt · plan_review CEO 把关意见", () => {
  it("有摘要时：结论上提 hero；Top2 风险常显；建议默认折叠", () => {
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: "方案整体可行，建议放行下游。",
          risks: ["成本估算偏乐观", "缺少回滚预案", "第三方 SLA 未知"],
          suggestions: ["先小流量灰度"],
        },
      }),
    ];
    renderPrompt();

    const block = screen.getByTestId("ceo-review-summary");
    expect(block).toBeTruthy();
    expect(screen.getByText("风险")).toBeTruthy();
    expect(screen.getByText(/另 1 风险/)).toBeTruthy();
    expect(screen.getByText(/1 建议/)).toBeTruthy();
    // 结论在 hero（非把关块内重复）
    expect(screen.getByText("方案整体可行，建议放行下游。")).toBeTruthy();
    expect(screen.getByText("成本估算偏乐观")).toBeTruthy();
    expect(screen.getByText("缺少回滚预案")).toBeTruthy();
    // 第 3 风险与建议默认折叠
    expect(screen.queryByText("第三方 SLA 未知")).toBeNull();
    expect(screen.queryByText("建议")).toBeNull();
    expect(screen.queryByText("先小流量灰度")).toBeNull();
    expect(screen.getByTestId("ceo-review-more-toggle")).toBeTruthy();

    expect(screen.getByText("计划复核 · 等你确认")).toBeTruthy();
    expect(screen.getByText("「调研」已完成")).toBeTruthy();
    // 产出摘要默认折叠：角色名可扫，全文不可见
    expect(screen.getByText(/· 调研/)).toBeTruthy();
    expect(screen.queryByText("方案就绪")).toBeNull();
    expect(screen.getByText("下游")).toBeTruthy();
    expect(screen.getByText("执行")).toBeTruthy();
  });

  it("展开把关详情后可见其余风险与建议", () => {
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: "可过",
          risks: ["风险甲", "风险乙", "风险丙"],
          suggestions: ["建议丁"],
        },
      }),
    ];
    renderPrompt();

    fireEvent.click(screen.getByTestId("ceo-review-more-toggle"));
    expect(screen.getByText("风险丙")).toBeTruthy();
    expect(screen.getByText("建议")).toBeTruthy();
    expect(screen.getByText("建议丁")).toBeTruthy();
  });

  it("展开产出摘要后可见 step summary", () => {
    pendingRef.current = [makePlanReview()];
    renderPrompt();

    expect(screen.queryByText("方案就绪")).toBeNull();
    fireEvent.click(screen.getByTestId("plan-review-steps-toggle"));
    expect(screen.getByText("方案就绪")).toBeTruthy();
  });

  it("absent（旧帧无 ceo_review）不渲染摘要区", () => {
    pendingRef.current = [makePlanReview()];
    renderPrompt();

    expect(screen.queryByTestId("ceo-review-summary")).toBeNull();
    expect(screen.queryByTestId("plan-review-gate-notes-hint")).toBeNull();
    expect(screen.getByText("计划复核 · 等你确认")).toBeTruthy();
    expect(screen.getByText("继续")).toBeTruthy();
  });

  it("llm 把关时继续按钮携带下发提示", () => {
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: "可过",
          risks: ["风险"],
          suggestions: [],
          source: "llm",
        },
      }),
    ];
    renderPrompt();
    expect(screen.getByTestId("plan-review-gate-notes-hint")).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "继续。继续后，把关要点将发给下游",
      }),
    ).toBeTruthy();
  });

  it("deterministic 把关不显示下发提示", () => {
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: "回落摘要",
          risks: ["风险"],
          suggestions: [],
          source: "deterministic",
        },
      }),
    ];
    renderPrompt();
    expect(screen.queryByTestId("plan-review-gate-notes-hint")).toBeNull();
  });

  it("仅结论、无风险建议时不渲染把关块（结论已在 hero）", () => {
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: "一切顺利，直接放行。",
          risks: [],
          suggestions: [],
        },
      }),
    ];
    renderPrompt();

    expect(screen.getByText("一切顺利，直接放行。")).toBeTruthy();
    expect(screen.queryByTestId("ceo-review-summary")).toBeNull();
  });

  it("仅部分字段时只渲染有内容的段（无空壳小标题）", () => {
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: "",
          risks: ["依赖外部接口稳定性"],
          suggestions: [],
        },
      }),
    ];
    renderPrompt();

    expect(screen.getByTestId("ceo-review-summary")).toBeTruthy();
    expect(screen.getByText("风险")).toBeTruthy();
    expect(screen.getByText("依赖外部接口稳定性")).toBeTruthy();
    expect(screen.queryByText("建议")).toBeNull();
    // ≤2 风险且无建议 → 无「详情」
    expect(screen.queryByTestId("ceo-review-more-toggle")).toBeNull();
  });

  it("长结论默认截断，可展开全文", () => {
    const long =
      "这是一段足够长的把关结论，用来验证默认三行截断与展开全文交互是否可用。" +
      "后续仍有补充说明，确保超过长度阈值后会出现展开入口，便于用户查看完整意见。";
    expect(long.length).toBeGreaterThan(60);
    pendingRef.current = [
      makePlanReview({
        ceoReview: {
          conclusion: long,
          risks: [],
          suggestions: [],
        },
      }),
    ];
    renderPrompt();
    expect(screen.getByTestId("plan-review-conclusion-toggle")).toBeTruthy();
    fireEvent.click(screen.getByTestId("plan-review-conclusion-toggle"));
    expect(screen.getByText("收起")).toBeTruthy();
  });
});
