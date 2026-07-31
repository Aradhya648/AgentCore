// @vitest-environment jsdom
/**
 * ask_user intent variants: proposal_pick (方案墙) / risk_ack (风险清单).
 */

import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AskUserCard, collectAskSelected } from "../CheckpointCard";
import type { AskUserContent } from "../ask/AskUserFields";

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
}));

afterEach(cleanup);

const proposalContent: AskUserContent = {
  question: "选哪条方案推进？",
  context: "三条路线成本与风险不同。",
  assumptions: [],
  questions: [
    {
      id: "q0",
      prompt: "选哪条方案？",
      kind: "choice",
      multiple: false,
      default: "",
      options: [
        { label: "方案 A：快速原型", detail: "一周内可验证" },
        { label: "方案 B：稳妥重构", detail: "两周，债务更少" },
        { label: "方案 C：外包试点", recommended: true },
      ],
    },
  ],
  styleOptions: [],
  formatOptions: [],
};

const riskContent: AskUserContent = {
  question: "哪些风险要在本轮处理？",
  context: "未勾选的项将记入后续 backlog。",
  assumptions: [],
  questions: [
    {
      id: "q0",
      prompt: "勾选要处理的风险",
      kind: "choice",
      multiple: true,
      default: "",
      options: [
        { label: "[高] 密钥轮换", detail: "生产密钥仍是默认值" },
        { label: "备份校验" },
        { label: "[中] 回滚演练", recommended: true },
      ],
    },
  ],
  styleOptions: [],
  formatOptions: [],
};

function renderCard(
  intent: "proposal_pick" | "risk_ack" | "daily_review",
  content: AskUserContent,
  onSubmit = vi.fn(),
) {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <AskUserCard content={content} intent={intent} onSubmit={onSubmit} />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

const dailyReviewContent: AskUserContent = {
  question: "确认要落盘的复盘提案？",
  context: "来自今日对话摘要。",
  assumptions: [],
  questions: [
    {
      id: "q0",
      prompt: "勾选要写入的项",
      kind: "choice",
      multiple: true,
      default: "",
      options: [
        {
          label: "偏好简洁回复",
          review_kind: "preference",
          body: "用户偏好短句答复",
        },
        {
          label: "主题：周报节奏",
          review_kind: "topic",
          body: "每周五整理周报",
        },
        {
          label: "规则：先问再改文件",
          review_kind: "rule",
          body: "改文件前先征得确认",
        },
      ],
    },
  ],
  styleOptions: [],
  formatOptions: [],
};

describe("AskUserCard intent variants", () => {
  it("proposal_pick 行式单选，推荐灰字；提交带 selected", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderCard("proposal_pick", proposalContent, onSubmit);

    expect(
      document.querySelector('[data-ask-intent="proposal_pick"]'),
    ).toBeTruthy();
    expect(
      document.querySelector('[data-ask-card="proposal_pick"]'),
    ).toBeTruthy();
    expect(screen.getByText("方案 A：快速原型")).toBeTruthy();
    expect(screen.getByText("一周内可验证")).toBeTruthy();
    expect(screen.getByText("推荐")).toBeTruthy();

    const adopt = screen.getByRole("button", { name: "采用此方案" });
    expect((adopt as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByText("方案 C：外包试点"));
    expect((adopt as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(adopt);
    expect(onSubmit).toHaveBeenCalledWith(
      "continue",
      "",
      ["方案 C：外包试点"],
      null,
      null,
    );
  });

  it("risk_ack 行式多选，严重度与建议处理灰字；提交带 selected", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderCard("risk_ack", riskContent, onSubmit);

    expect(document.querySelector('[data-ask-intent="risk_ack"]')).toBeTruthy();
    expect(document.querySelector('[data-ask-card="risk_ack"]')).toBeTruthy();
    expect(screen.getByText("密钥轮换")).toBeTruthy();
    expect(screen.getByText("高")).toBeTruthy();
    expect(screen.getByText(/建议处理/)).toBeTruthy();
    expect(screen.getByText("备份校验")).toBeTruthy();

    fireEvent.click(screen.getByText("密钥轮换"));
    fireEvent.click(screen.getByText("回滚演练"));
    fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));

    expect(onSubmit).toHaveBeenCalledWith(
      "continue",
      "",
      ["[高] 密钥轮换", "[中] 回滚演练"],
      null,
      null,
    );
  });

  it("daily_review 默认全选，取消勾选后提交带 selected", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderCard("daily_review", dailyReviewContent, onSubmit);

    expect(
      document.querySelector('[data-ask-intent="daily_review"]'),
    ).toBeTruthy();
    expect(
      document.querySelector('[data-ask-card="daily_review"]'),
    ).toBeTruthy();
    expect(screen.getByText("偏好简洁回复")).toBeTruthy();
    expect(screen.getByText(/偏好 · 用户偏好短句答复/)).toBeTruthy();
    expect(
      screen.getByText(/确认后服务端直接写入记忆\/规则\/文档/),
    ).toBeTruthy();

    // Seed all three; uncheck one.
    fireEvent.click(screen.getByText("主题：周报节奏"));
    fireEvent.click(screen.getByRole("button", { name: /确认落盘/ }));

    expect(onSubmit).toHaveBeenCalledWith(
      "continue",
      "",
      ["偏好简洁回复", "规则：先问再改文件"],
      null,
      null,
    );
  });

  it("kickoff wire 走通用澄清壳；交付形态 continue 直传 format_id 与 selected fN", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const content: AskUserContent = {
      question: "演讲怎么交付？",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [
        { id: "f0", label: "PowerPoint（.pptx）" },
        { id: "f1", label: "Marp Markdown" },
      ],
    };
    render(
      <MemoryRouter>
        <TooltipProvider>
          <AskUserCard content={content} intent="kickoff" onSubmit={onSubmit} />
        </TooltipProvider>
      </MemoryRouter>,
    );
    expect(document.querySelector('[data-ask-intent="decision"]')).toBeTruthy();
    expect(document.querySelector('[data-ask-card="decision"]')).toBeTruthy();
    expect(screen.getByText("交付形态")).toBeTruthy();
    fireEvent.click(screen.getByText("Marp Markdown"));
    fireEvent.click(screen.getByRole("button", { name: /^提交$/ }));
    expect(onSubmit).toHaveBeenCalledWith(
      "continue",
      expect.stringContaining("· 形态：Marp Markdown"),
      ["f1"],
      null,
      "f1",
    );
  });

  it("collectAskSelected 扁平化多题 picks", () => {
    expect(
      collectAskSelected(proposalContent, { q0: ["方案 A：快速原型"] }, {}, {}),
    ).toEqual(["方案 A：快速原型"]);
  });
});
