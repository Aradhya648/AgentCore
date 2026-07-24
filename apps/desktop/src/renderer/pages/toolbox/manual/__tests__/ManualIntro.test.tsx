// @vitest-environment jsdom
import { ManualIntro } from "@/pages/toolbox/manual/ManualIntro";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

describe("ManualIntro", () => {
  it("renders compressed intro: what + mindset + 5 分钟上手", () => {
    render(
      <MemoryRouter initialEntries={["/toolbox/manual/intro"]}>
        <ManualIntro />
      </MemoryRouter>,
    );
    expect(screen.getByText("这是什么")).toBeTruthy();
    expect(screen.getByText("核心心智：你是领导者")).toBeTruthy();
    expect(screen.getByText("5 分钟上手")).toBeTruthy();
    expect(screen.queryByText("快速上手")).toBeNull();
    // 竞品对比已删
    expect(screen.queryByText(/在 ChatGPT/)).toBeNull();
    expect(screen.queryByText(/在 Cursor/)).toBeNull();
    expect(screen.getByText(/约 5 分钟/)).toBeTruthy();
    expect(screen.getByText("直接开聊（平台额度）")).toBeTruthy();
    expect(screen.getByText("说目标")).toBeTruthy();
  });
});
