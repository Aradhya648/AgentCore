import type { ProcessStep } from "@agentcore/contract-types";
import { describe, expect, it } from "vitest";
import { formatMessageExport, formatProcessExport } from "../messageExport";

const steps: ProcessStep[] = [
  { kind: "reasoning", text: "先查资料" },
  {
    kind: "tool",
    id: "t1",
    tool_name: "web_search",
    arguments: { query: "AgentCore" },
    result: "ok",
    status: "success",
  },
  { kind: "content", text: "我先看一下。" },
  { kind: "content", text: "最终方案如下。" },
];

describe("formatProcessExport", () => {
  it("orders narration and tool lines for copy", () => {
    const text = formatProcessExport(steps);
    expect(text).toContain("【思考】");
    expect(text).toContain("先查资料");
    expect(text).toContain("Search web");
    expect(text).toContain("AgentCore");
    expect(text).toContain("我先看一下。");
    expect(text).toContain("最终方案如下。");
  });

  it("returns empty for missing process", () => {
    expect(formatProcessExport(undefined)).toBe("");
    expect(formatProcessExport([])).toBe("");
  });
});

describe("formatMessageExport", () => {
  it("defaults to deliverable-only", () => {
    expect(formatMessageExport("最终方案如下。", steps, "deliverable")).toBe(
      "最终方案如下。",
    );
  });

  it("includes process without duplicating trailing deliverable", () => {
    const text = formatMessageExport("最终方案如下。", steps, "with_process");
    expect(text.startsWith("【过程】")).toBe(true);
    expect(text).toContain("我先看一下。");
    expect(text).toContain("最终方案如下。");
    expect(text).not.toContain("【交付】");
  });

  it("appends deliverable when timeline lacks it", () => {
    const processOnly: ProcessStep[] = [
      { kind: "reasoning", text: "想一下" },
      {
        kind: "tool",
        id: "t1",
        tool_name: "grep",
        arguments: { pattern: "foo" },
        result: null,
        status: "success",
      },
    ];
    const text = formatMessageExport("交付正文", processOnly, "with_process");
    expect(text).toContain("【过程】");
    expect(text).toContain("【交付】");
    expect(text).toContain("交付正文");
  });

  it("falls back to deliverable when process is empty", () => {
    expect(formatMessageExport("仅交付", undefined, "with_process")).toBe(
      "仅交付",
    );
  });
});
