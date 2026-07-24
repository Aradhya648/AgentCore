// @vitest-environment jsdom

import { DebriefSection } from "@/components/chat/detail/sections/RunDebrief";
import type { RunDebrief } from "@/types/events";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/chat/Markdown", () => ({
  Markdown: ({ content }: { content: string }) => <div>{content}</div>,
}));

const baseDebrief: RunDebrief = {
  summary: "交叉验证完成",
  key_points: ["共识：一周内需清晰立场"],
  assumptions: "争议事实以公开报道为准",
  next_steps: "若用户同意，建议开辩",
};

const motionCard = {
  motion: "品牌是否应立即终止与该代言人的联名合作",
  sides: [
    { key: "terminate", name: "立即终止方", stance: "应立刻切割止损" },
    { key: "hold", name: "冷静观望方", stance: "证据未定不宜仓促解约" },
  ],
  fact_pointers: ["#r1", "#r3", "notes/endorsement.md"],
  rationale: "法律风险与品牌声誉的取舍无法靠继续取证收敛。",
  form: "debate" as const,
};

describe("DebriefSection", () => {
  it("renders core brief fields without a motion card", () => {
    render(<DebriefSection debrief={baseDebrief} />);
    expect(screen.getByText("结论")).toBeTruthy();
    expect(screen.getByText("交叉验证完成")).toBeTruthy();
    expect(screen.queryByText("命题卡")).toBeNull();
  });

  it("renders a structured motion card block when present", () => {
    render(
      <DebriefSection debrief={{ ...baseDebrief, motion_card: motionCard }} />,
    );
    expect(screen.getByText("命题卡")).toBeTruthy();
    expect(screen.getByText("命题")).toBeTruthy();
    expect(screen.getByText(motionCard.motion)).toBeTruthy();
    expect(screen.getByText("立即终止方")).toBeTruthy();
    expect(screen.getByText(/应立刻切割止损/)).toBeTruthy();
    expect(screen.getByText("#r1")).toBeTruthy();
    expect(screen.getByText("为何需对抗")).toBeTruthy();
    expect(screen.getByText(motionCard.rationale)).toBeTruthy();
    expect(screen.getByText("形式")).toBeTruthy();
    expect(screen.getByText("正反")).toBeTruthy();
  });

  it("labels red_team / roundtable forms", () => {
    const { rerender } = render(
      <DebriefSection
        debrief={{
          ...baseDebrief,
          motion_card: { ...motionCard, form: "red_team" },
        }}
      />,
    );
    expect(screen.getByText("红队")).toBeTruthy();
    rerender(
      <DebriefSection
        debrief={{
          ...baseDebrief,
          motion_card: { ...motionCard, form: "roundtable" },
        }}
      />,
    );
    expect(screen.getByText("圆桌")).toBeTruthy();
  });
});
