// @vitest-environment jsdom
/**
 * 质询块「审计清单」交互：
 * - 逐条 Q↔A：中性原文 + 客观状态（作答中/失败/未作答）；折叠预览纯文本、展开看 markdown；
 * - 无侧栏「展开全文」（会暴露原始 blob）；名字行仍对齐 SpeakerBlock → showRunDetail；
 * - 空态（exchanges 为空）只保留「暂无质询问答」提示，钻取走名字行侧栏。
 */

import type { RunNode } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DebateCrossExamView } from "../../model";
import { CrossExamSection } from "../CrossExamSection";

vi.mock("@/components/chat/Markdown", () => ({
  Markdown: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

const PLAIN_ANSWER = "已含尾部风险，熔断成本由平台承担。";

function answerRun(
  id = "mod_r1_cx_pro",
  status: RunNode["status"] = "completed",
): RunNode {
  return {
    id,
    agentId: id,
    status,
    kind: "agent",
    parentRunId: null,
    continuesRunId: null,
    receivedContext: [],
  } as unknown as RunNode;
}

function cxView(
  overrides: Partial<DebateCrossExamView> = {},
): DebateCrossExamView {
  return {
    targetKey: "pro",
    stance: "pro",
    targetName: "支持方",
    targetColorVar: "var(--debate-pro)",
    exchanges: [
      {
        question: "收益口径是否含尾部风险？",
        answer: PLAIN_ANSWER,
      },
    ],
    answerRun: answerRun(),
    ...overrides,
  };
}

function renderSection(cx: DebateCrossExamView) {
  return render(
    <CrossExamSection exchanges={[cx]} messageId="m1" sceneKey="m1:cx:r1" />,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CrossExamSection 审计清单", () => {
  it("折叠态：中性 Q→A 预览；无褒贬徽章、无双图标、无展开全文", () => {
    renderSection(cxView());

    const row = screen.getByRole("button", { expanded: false });
    expect(screen.queryByText("正面回应")).toBeNull();
    expect(screen.queryByText("回避")).toBeNull();
    expect(screen.getByText(/1 条质询/)).toBeTruthy();
    expect(row.textContent).toMatch(/收益口径是否含尾部风险/);
    expect(row.textContent).toMatch(/已含尾部风险/);
    expect(screen.queryByRole("button", { name: "展开全文" })).toBeNull();
  });

  it("整行展开后看完整 markdown 答案，问题仍可见", () => {
    renderSection(cxView());

    fireEvent.click(screen.getByRole("button", { expanded: false }));

    expect(screen.getByTestId("markdown").textContent).toBe(PLAIN_ANSWER);
    expect(screen.getByText(/收益口径是否含尾部风险/)).toBeTruthy();
    expect(screen.getByRole("button", { expanded: true })).toBeTruthy();
  });

  it("疑似原始 JSON blob 的折叠预览回落到占位，不原样露出", () => {
    const blob = '[{"q":1,"a":"秘密口径"}]';
    renderSection(
      cxView({
        exchanges: [{ question: "口径？", answer: blob }],
      }),
    );

    const row = screen.getByRole("button", { expanded: false });
    expect(row.textContent).toContain("点开查看");
    expect(row.textContent).not.toContain("秘密口径");
    expect(row.textContent).not.toMatch(/\[\{/);
  });

  it("## 质询应答 blob 折叠预览回落占位", () => {
    renderSection(
      cxView({
        exchanges: [
          {
            question: "成本谁担？",
            answer: "## 质询应答\n\n平台承担。",
          },
        ],
      }),
    );

    const row = screen.getByRole("button", { expanded: false });
    expect(row.textContent).toContain("点开查看");
    expect(row.textContent).not.toContain("质询应答");
  });

  it("客观状态：待答 / 作答失败 / 未作答（无正面回应·回避褒贬）", () => {
    renderSection(
      cxView({
        exchanges: [{ question: "有答文也不贴褒贬", answer: "改天再说。" }],
      }),
    );
    expect(screen.queryByText("回避")).toBeNull();
    expect(screen.queryByText("正面回应")).toBeNull();
    cleanup();

    renderSection(
      cxView({
        exchanges: [{ question: "待答？", answer: "" }],
        answerRun: answerRun("mod_r1_cx_pro", "running"),
      }),
    );
    expect(screen.getByText("待答")).toBeTruthy();
    expect(screen.getAllByText("作答中…").length).toBeGreaterThan(0);
    cleanup();

    renderSection(
      cxView({
        exchanges: [{ question: "失败？", answer: "" }],
        answerRun: answerRun("mod_r1_cx_pro", "failed"),
      }),
    );
    expect(screen.getAllByText("作答失败").length).toBeGreaterThan(0);
  });

  it("收场无作答（非失败）→ 未作答徽章", () => {
    renderSection(
      cxView({
        exchanges: [{ question: "未答题？", answer: "" }],
      }),
    );
    expect(screen.getAllByText("未作答").length).toBeGreaterThan(0);
    expect(screen.queryByText("回避")).toBeNull();
  });

  it("空态（exchanges 为空）保留提示，无展开全文链接", () => {
    renderSection(cxView({ exchanges: [] }));

    expect(screen.getByText("暂无质询问答")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "展开全文" })).toBeNull();
  });

  it("无 run 时名字行不是按钮；有 run 时点名字打开详情侧栏", () => {
    renderSection(cxView({ exchanges: [], answerRun: null }));
    expect(screen.queryByRole("button", { name: /支持方/ })).toBeNull();
    cleanup();

    const showRunDetail = vi.fn();
    useSidePanelStore.setState({ showRunDetail });
    renderSection(cxView());

    fireEvent.click(screen.getByRole("button", { name: /支持方/ }));

    expect(showRunDetail).toHaveBeenCalledWith(
      "m1",
      "mod_r1_cx_pro",
      "支持方 · 质询作答",
    );
  });

  it("markdown 记号在折叠预览中被剥离", () => {
    renderSection(
      cxView({
        exchanges: [
          {
            question: "证据？",
            answer: "**已核实**：灰度预案 v2 覆盖。",
          },
        ],
      }),
    );

    const row = screen.getByRole("button", { expanded: false });
    expect(row.textContent).toMatch(/已核实：灰度预案/);
    expect(row.textContent).not.toContain("**已核实**");
  });

  it("split 时 target key 非 pro/con 也按 stance 分列并排（自定 key 回归）", () => {
    const { container } = render(
      <CrossExamSection
        exchanges={[
          cxView({
            targetKey: "原告",
            targetName: "原告",
            stance: "pro",
            answerRun: answerRun("cx_plaintiff"),
          }),
          cxView({
            targetKey: "被告",
            targetName: "被告",
            stance: "con",
            answerRun: answerRun("cx_defendant"),
          }),
        ]}
        messageId="m1"
        sceneKey="m1:cx:r1"
        layoutMode="split"
      />,
    );

    expect(container.querySelector(".debate-split-grid")).toBeTruthy();
    expect(screen.getByRole("button", { name: /原告/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /被告/ })).toBeTruthy();
  });
});
