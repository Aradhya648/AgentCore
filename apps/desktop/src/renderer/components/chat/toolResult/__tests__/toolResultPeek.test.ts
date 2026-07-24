import { describe, expect, it } from "vitest";
import {
  type ToolResultData,
  hasToolResultBody,
  toolResultPeek,
} from "../ToolResultView";

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

describe("toolResultPeek", () => {
  it("summarizes a web_search by hit count", () => {
    expect(
      toolResultPeek(
        data({
          toolName: "web_search",
          display: { query: "q", results: [{}, {}] },
        }),
      ),
    ).toBe("2 results");
  });

  it("summarizes a read_url as「标题 · 域名」", () => {
    expect(
      toolResultPeek(
        data({
          toolName: "read_url",
          display: {
            url: "https://weather.example.com/sz",
            title: "深圳天气",
            site: "weather.example.com",
            snippet: "多云转晴",
            content: "正文内容…",
          },
          // Model-facing JSON must NOT leak into the peek.
          result:
            '{"url":"https://weather.example.com/sz","title":"深圳天气","content":"正文内容…"}',
        }),
      ),
    ).toBe("深圳天气 · weather.example.com");
  });

  it("shows the exit code for a failed code_execute", () => {
    expect(
      toolResultPeek(
        data({
          toolName: "code_execute",
          display: { stdout: "", stderr: "boom", exit_code: 1 },
        }),
      ),
    ).toBe("退出码 1");
  });

  it("shows the first stdout line for a successful code_execute", () => {
    expect(
      toolResultPeek(
        data({
          toolName: "code_execute",
          display: { stdout: "hello\nworld", stderr: "", exit_code: 0 },
        }),
      ),
    ).toBe("hello");
  });

  it("names the path for a str_replace edit", () => {
    expect(
      toolResultPeek(
        data({
          toolName: "str_replace",
          args: { path: "a.ts", old_string: "x", new_string: "y" },
        }),
      ),
    ).toBe("已编辑 a.ts");
  });

  it("names the path for a file_write", () => {
    expect(
      toolResultPeek(
        data({ toolName: "file_write", args: { path: "a.ts", content: "x" } }),
      ),
    ).toBe("已写入 a.ts");
  });

  it("names the topic for a consult_memory", () => {
    expect(
      toolResultPeek(
        data({
          toolName: "consult_memory",
          display: { topic: "部署流程" },
          result: "## 笔记\n- x",
        }),
      ),
    ).toBe("部署流程");
  });

  it("falls back to the first non-empty result line", () => {
    expect(
      toolResultPeek(data({ toolName: "grep", result: "match line\nmore" })),
    ).toBe("match line");
  });
});

describe("hasToolResultBody", () => {
  it("is false while the tool is still running", () => {
    expect(hasToolResultBody(data({ status: "running", result: "x" }))).toBe(
      false,
    );
  });

  it("is true when a rich display is present", () => {
    expect(
      hasToolResultBody(
        data({ toolName: "web_search", display: { query: "q", results: [] } }),
      ),
    ).toBe(true);
  });

  it("is true for a file_write derived from its content arg", () => {
    expect(
      hasToolResultBody(
        data({
          toolName: "file_write",
          args: { path: "a", content: "x" },
          result: null,
        }),
      ),
    ).toBe(true);
  });

  it("is false for an empty text result", () => {
    expect(hasToolResultBody(data({ toolName: "grep", result: "  " }))).toBe(
      false,
    );
  });
});
