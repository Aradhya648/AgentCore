// @vitest-environment jsdom
/**
 * 边干边上报默认折叠为一行摘要，点击展开全文 + 假设。
 */
import { EscalationCard } from "@/components/chat/EscalationCard";
import type { RunEscalation } from "@/stores/execution";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function raisedEsc(overrides: Partial<RunEscalation> = {}): RunEscalation {
  return {
    id: "esc-raised",
    question:
      "本轮工具清单未包含 file_write，无法将第5轮审查报告落盘。\n请授予写盘或由主管代为持久化。",
    assumption: "主管将据正文内容持久化报告或于下波授予写盘工具",
    blocking: false,
    status: "raised",
    answer: null,
    kind: "dep",
    questions: [],
    ...overrides,
  };
}

describe("EscalationCard · raised collapse", () => {
  it("默认折叠为一行摘要，点击可展开全文与假设", () => {
    // Spread `role` — prop is teammate display name, not ARIA role (biome a11y).
    render(
      <EscalationCard
        escalation={raisedEsc()}
        conversationId="conv-1"
        interactive
        {...{ role: "渲染与几何层审查员" }}
      />,
    );

    const toggle = screen.getByRole("button", {
      name: "展开 渲染与几何层审查员 边干边上报",
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.querySelector(".line-clamp-1")).toBeTruthy();
    expect(toggle.querySelector(".whitespace-pre-wrap")).toBeNull();
    expect(toggle.textContent).not.toContain("已按假设继续");

    fireEvent.click(toggle);
    const opened = screen.getByRole("button", {
      name: "收起 渲染与几何层审查员 边干边上报",
    });
    expect(opened.getAttribute("aria-expanded")).toBe("true");
    expect(opened.querySelector(".whitespace-pre-wrap")).toBeTruthy();
    expect(opened.querySelector(".line-clamp-1")).toBeNull();
    expect(opened.textContent).toContain("请授予写盘或由主管代为持久化");
    expect(opened.textContent).toContain(
      "已按假设继续：主管将据正文内容持久化报告或于下波授予写盘工具",
    );
  });
});
