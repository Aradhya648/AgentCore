// @vitest-environment jsdom
/**
 * Render test for the consult_memory tool-result card (记忆文件夹化 §六 · 渐进披露 可视化):
 * the CEO's pulled 记忆主题笔记 shows as a「查阅记忆：<主题>」header with the note body
 * verbatim below. The block comment here detaches the @vitest-environment directive from
 * the import block so organizeImports keeps it file-leading.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { type ToolResultData, ToolResultView } from "../ToolResultView";

afterEach(cleanup);

function data(p: Partial<ToolResultData>): ToolResultData {
  return {
    toolName: "x",
    args: {},
    result: null,
    display: null,
    status: "success",
    ...p,
  };
}

describe("ToolResultView · consult_memory", () => {
  it("renders the pulled memory note as a「查阅记忆：<主题>」card with its body", () => {
    render(
      <ToolResultView
        data={data({
          toolName: "consult_memory",
          display: { topic: "部署流程" },
          result: "## 笔记\n- 用 pnpm dev 起前端",
        })}
      />,
    );
    expect(screen.getByText("查阅记忆：")).toBeTruthy();
    expect(screen.getByText("部署流程")).toBeTruthy();
    // The full note body the CEO consulted is shown verbatim, expandable below.
    expect(screen.getByText(/用 pnpm dev 起前端/)).toBeTruthy();
  });

  it("shows the header even when the note body is empty", () => {
    render(
      <ToolResultView
        data={data({
          toolName: "consult_memory",
          display: { topic: "项目背景" },
          result: "",
        })}
      />,
    );
    expect(screen.getByText("查阅记忆：")).toBeTruthy();
    expect(screen.getByText("项目背景")).toBeTruthy();
  });
});

describe("ToolResultView · read_url", () => {
  it("renders a source-style header + body from display (not JSON result)", () => {
    render(
      <ToolResultView
        data={data({
          toolName: "read_url",
          display: {
            url: "https://weather.example.com/sz",
            title: "深圳天气",
            site: "weather.example.com",
            snippet: "多云转晴",
            content: "今天气温 20-28 度。",
          },
          result:
            '{"url":"https://weather.example.com/sz","title":"深圳天气","content":"今天气温 20-28 度。"}',
        })}
      />,
    );
    const link = screen.getByRole("link", { name: /深圳天气/ });
    expect(link.getAttribute("href")).toBe("https://weather.example.com/sz");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByText("weather.example.com")).toBeTruthy();
    expect(screen.getByText("今天气温 20-28 度。")).toBeTruthy();
    // Raw JSON must not appear — display is the sole render source.
    expect(screen.queryByText(/\{"url":/)).toBeNull();
  });
});
