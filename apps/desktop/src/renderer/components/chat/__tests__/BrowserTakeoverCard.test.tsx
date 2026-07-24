// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrowserTakeoverCard } from "../BrowserTakeoverCard";

/**
 * L3「团队浏览器」M2 接管标记卡 (BrowserTakeoverCard) 渲染单测：
 * - 「用户接管了浏览器 · N分M秒」时长文案；不足 1 分显「M秒」。
 * - endedAt 为空（异常未归还）→ 退化为无时长文案。
 */
describe("BrowserTakeoverCard", () => {
  it("renders 用户接管了浏览器 + N分M秒 duration", () => {
    render(
      <BrowserTakeoverCard
        takeover={{
          id: "t1",
          startedAt: "2026-07-20T00:00:00Z",
          endedAt: "2026-07-20T00:01:05Z",
        }}
      />,
    );
    expect(screen.getByText(/用户接管了浏览器 · 1分5秒/)).toBeTruthy();
  });

  it("renders a sub-minute takeover as bare seconds", () => {
    render(
      <BrowserTakeoverCard
        takeover={{
          id: "t2",
          startedAt: "2026-07-20T00:00:00Z",
          endedAt: "2026-07-20T00:00:30Z",
        }}
      />,
    );
    expect(screen.getByText(/用户接管了浏览器 · 30秒/)).toBeTruthy();
  });

  it("renders without a duration when the takeover has not ended", () => {
    render(
      <BrowserTakeoverCard
        takeover={{
          id: "t3",
          startedAt: "2026-07-20T00:00:00Z",
          endedAt: null,
        }}
      />,
    );
    expect(screen.getByText("用户接管了浏览器")).toBeTruthy();
  });
});
