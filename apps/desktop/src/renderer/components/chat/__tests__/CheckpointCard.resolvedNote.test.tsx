// @vitest-environment jsdom
/**
 * 已定案检查点存根：默认收起成单行（结论 + 问题摘要），点击展开见问题全文、
 * 选项 chips 与答复明细。收起态只保留一行，明细/选项均随卡一起收起。
 */

import type { CheckpointDisplay } from "@/stores/conversation";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CheckpointCard } from "../CheckpointCard";

afterEach(cleanup);

const resolvedKickoff: CheckpointDisplay = {
  id: "cp-1",
  question: "关于论文有几个方向想先跟你对齐",
  context: "",
  assumptions: [],
  questions: [],
  styleOptions: [],
  formatOptions: [],
  intent: "kickoff",
  status: "resolved",
  decision: "continue",
  note: "就按这个方案开做：\n· 定位？：综述型\n· 读者？：公开发表\n· 篇幅？：精简干货",
  selected: [],
};

describe("ResolvedCheckpoint 单行折叠", () => {
  it("默认收起单行：结论+问题摘要常驻，答复明细隐藏；点击展开见完整 note", () => {
    render(<CheckpointCard checkpoint={resolvedKickoff} />);

    // 收起单行：结论标签 + 问题摘要。
    expect(screen.getByText("已按方案开做")).toBeTruthy();
    expect(screen.getByText(resolvedKickoff.question)).toBeTruthy();

    // note 明细收起时不渲染。
    expect(document.body.textContent).not.toContain("就按这个方案开做：");
    expect(document.body.textContent).not.toContain("· 定位？：综述型");

    // 展开：点击存根头部 → 答复明细出现。
    fireEvent.click(screen.getByText("已按方案开做"));
    expect(document.body.textContent).toContain("就按这个方案开做：");
    expect(document.body.textContent).toContain("· 定位？：综述型");
    expect(document.body.textContent).toContain("· 篇幅？：精简干货");
  });

  it("proposal_pick：选项 chips 收起时随卡隐藏、展开后显示", () => {
    const resolvedProposal: CheckpointDisplay = {
      ...resolvedKickoff,
      id: "cp-2",
      intent: "proposal_pick",
      question: "选哪条方案推进？",
      selected: ["方案 C：外包试点"],
      note: "",
    };
    render(<CheckpointCard checkpoint={resolvedProposal} />);

    // 收起：仅结论 + 问题摘要，chip 不显示。
    expect(screen.getByText("已选定方案")).toBeTruthy();
    expect(document.body.textContent).not.toContain("方案 C：外包试点");

    // 展开：chip 显示。
    fireEvent.click(screen.getByText("已选定方案"));
    expect(screen.getByText("方案 C：外包试点")).toBeTruthy();
  });
});
