// @vitest-environment jsdom
/**
 * 拍板中心 · plan_review：CEO 把关意见（conclusion / risks / suggestions）随
 * `plan_review_required.ceo_review` 渲染进 ResumePrompt；absent（旧帧 / 无摘要）
 * 不渲染摘要区（不留空壳）。
 *
 * 三区布局：决策头（眉题+标题+结论）→ 上下文默认收（风险/建议与产出→下游同行
 * 次要 meta）→ 操作区贴底（常驻备注 + 调整/停止/继续）；llm 下发提示收进继续
 * 按钮 tooltip。
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
    question: "",
    context: "",
    assumptions: [],
    questions: [],
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
  it("有摘要时：结论上提；风险建议与产出同行 meta；详情折叠；备注常驻", () => {
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
    expect(screen.getByText("3 风险 · 1 建议")).toBeTruthy();
    expect(screen.getByTestId("ceo-review-more-toggle")).toBeTruthy();
    // 结论在 hero；风险正文默认不露
    expect(screen.getByText("方案整体可行，建议放行下游。")).toBeTruthy();
    expect(screen.queryByText("成本估算偏乐观")).toBeNull();
    expect(screen.queryByText("缺少回滚预案")).toBeNull();
    expect(screen.queryByText("第三方 SLA 未知")).toBeNull();
    expect(screen.queryByText("先小流量灰度")).toBeNull();

    expect(screen.getByText("计划复核 · 等你确认")).toBeTruthy();
    expect(screen.getByText("「调研」已完成")).toBeTruthy();
    // 产出摘要默认折叠：角色名可扫，全文不可见
    expect(screen.getByText(/· 调研/)).toBeTruthy();
    expect(screen.queryByText("方案就绪")).toBeNull();
    expect(screen.getByText("下游")).toBeTruthy();
    expect(screen.getByText("执行")).toBeTruthy();
    // 备注常驻，无「添加备注」折叠入口
    expect(screen.getByTestId("plan-review-note")).toBeTruthy();
    expect(screen.queryByTestId("plan-review-note-toggle")).toBeNull();
    expect(screen.getByPlaceholderText("可选备注；调整时必填")).toBeTruthy();
  });

  it("展开把关详情后可见全部风险与建议", () => {
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
    expect(screen.getByText("风险")).toBeTruthy();
    expect(screen.getByText("风险甲")).toBeTruthy();
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

  it("仅风险时摘要芯片可展开（无空壳小标题）", () => {
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
    expect(screen.getByText("1 风险")).toBeTruthy();
    expect(screen.queryByText("依赖外部接口稳定性")).toBeNull();
    fireEvent.click(screen.getByTestId("ceo-review-more-toggle"));
    expect(screen.getByText("风险")).toBeTruthy();
    expect(screen.getByText("依赖外部接口稳定性")).toBeTruthy();
    expect(screen.queryByText("建议")).toBeNull();
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

  it("备注输入框默认常驻", () => {
    pendingRef.current = [makePlanReview()];
    renderPrompt();

    expect(screen.getByTestId("plan-review-note")).toBeTruthy();
    expect(screen.queryByTestId("plan-review-note-toggle")).toBeNull();
  });

  it("无备注时点「调整」只 focus 备注框而不提交", async () => {
    const { submitInteraction } = await import("@/services/interactionSubmit");
    pendingRef.current = [makePlanReview()];
    renderPrompt();

    fireEvent.click(screen.getByRole("button", { name: "调整" }));
    expect(screen.getByTestId("plan-review-note")).toBeTruthy();
    expect(submitInteraction).not.toHaveBeenCalled();
  });
});
