// @vitest-environment jsdom
/**
 * 三维拆分展示单元：中性配色、罚分可读、净分格式。
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { DebateScoreView } from "../../model";
import {
  SCORE_DIMENSIONS,
  ScoreBreakdown,
  formatNetTotal,
} from "../ScoreBreakdown";

function score(overrides: Partial<DebateScoreView> = {}): DebateScoreView {
  return {
    sideKey: "pro",
    name: "正方",
    colorVar: "var(--debate-side-pro)",
    argument: 4,
    engagement: 3,
    evidence: 2,
    penalties: [],
    note: "",
    total: 9,
    ...overrides,
  };
}

afterEach(() => cleanup());

describe("formatNetTotal", () => {
  it("正数带 +，零与负数原样", () => {
    expect(formatNetTotal(9)).toBe("+9");
    expect(formatNetTotal(0)).toBe("0");
    expect(formatNetTotal(-2)).toBe("-2");
  });
});

describe("ScoreBreakdown", () => {
  it("常驻展示三维短标签与分值，无褒贬色类", () => {
    const { container } = render(<ScoreBreakdown score={score()} />);
    for (const dim of SCORE_DIMENSIONS) {
      expect(screen.getByText(dim.label)).toBeTruthy();
    }
    expect(screen.getByText("4")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    const html = container.innerHTML;
    expect(html).not.toMatch(
      /text-success|text-destructive|bg-success|bg-destructive/,
    );
  });

  it("罚分可展开列出具体条目", () => {
    render(
      <ScoreBreakdown
        score={score({
          penalties: ["以未证实的尾部风险当既定事实"],
          total: 8,
        })}
        penalties="expandable"
      />,
    );
    expect(screen.getByText(/罚分 · 1/)).toBeTruthy();
    expect(screen.queryByText("以未证实的尾部风险当既定事实")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /罚分 · 1/ }));
    expect(screen.getByText("以未证实的尾部风险当既定事实")).toBeTruthy();
  });

  it("penalties=inline 直接可读列出", () => {
    render(
      <ScoreBreakdown
        score={score({ penalties: ["循环论证", "无据硬拗"] })}
        penalties="inline"
      />,
    );
    expect(screen.getByText(/罚分 2：循环论证；无据硬拗/)).toBeTruthy();
  });
});
